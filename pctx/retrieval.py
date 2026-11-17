"""Shared, deterministic retrieval over public canonical records."""
from __future__ import annotations

import json
from pathlib import Path
import re
import unicodedata

from .architecture import load_architecture
from .security import secret_matches
from .storage import load_records
from .history import payload

# Explicit vocabulary aliases, not a semantic model or inferred translation.
_ALIASES = {
    'autenticacion': 'auth', 'authentication': 'auth', 'authenticate': 'auth',
    'sesion': 'session', 'sessions': 'session', 'sesiones': 'session',
    'pruebas': 'test', 'tests': 'test', 'testing': 'test',
    'archivo': 'file', 'archivos': 'file', 'files': 'file',
    'restricciones': 'constraint', 'constraints': 'constraint',
}
_STOP = {'the', 'and', 'for', 'with', 'from', 'this', 'that', 'los', 'las', 'una',
         'del', 'para', 'con', 'que', 'sin', 'por', 'fix', 'repair', 'corregir'}
_TYPE = {'constraint': 12, 'handoff': 11, 'next_action': 10, 'decision': 9,
         'issue': 8, 'procedure': 7, 'fact': 6, 'attempt': 5, 'note': 3, 'unknown': 2}


def words(text: str) -> set[str]:
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    text = ''.join(c for c in unicodedata.normalize('NFKD', text.lower()) if not unicodedata.combining(c))
    return {_ALIASES.get(w, w) for w in re.findall(r'[^\W_]+', text, re.UNICODE)
            if len(w) >= 3 and w not in _STOP}


def visible_records(root: Path) -> list[dict]:
    from .freshness import project
    return project(root, [r for r in load_records(root) if r.get('sensitivity') not in {'private', 'secret'}
            and not secret_matches(json.dumps(r, ensure_ascii=False))])


def _paths(record: dict) -> list[str]:
    return [str(e.get('path', '')) for e in record.get('evidence', []) if isinstance(e, dict) and e.get('path')]


def _component_matches(record: dict, component: str) -> bool:
    component = component.strip().replace('\\', '/').rstrip('/')
    scope = str(record.get('scope', '')).rstrip('/')
    return scope == component or scope.startswith(component + '/') or any(
        p == component or p.startswith(component + '/') for p in _paths(record))


def _related_words(root: Path, query: set[str]) -> set[str]:
    graph = load_architecture(root)
    nodes = {str(n.get('id')): words(str(n.get('label', ''))) for section in ('generated', 'custom')
             for n in graph[section]['nodes']}
    seeds = {nid for nid, tokens in nodes.items() if nid != 'project' and tokens & query}
    neighbors: set[str] = set()
    edges = [e for section in ('generated', 'custom') for e in graph[section]['edges']]
    for edge in sorted(edges, key=lambda e: (str(e.get('source')), str(e.get('target')))):
        if edge.get('label') in {'contains', 'defines', 'configures'}:
            continue
        a, b = str(edge.get('source')), str(edge.get('target'))
        if a in seeds and b not in seeds and b != 'project':
            neighbors.add(b)
        if b in seeds and a not in seeds and a != 'project':
            neighbors.add(a)
    return set().union(*(nodes.get(n, set()) for n in sorted(neighbors)[:12])) if neighbors else set()


def rank_records(root: Path, records: list[dict], query: str) -> list[dict]:
    query_words = words(query)
    related = _related_words(root, query_words) if query_words else set()
    result = []
    for record in records:
        evidence = words(' '.join(_paths(record)))
        scope = words(str(record.get('scope', '')))
        text = words(' '.join(str(record.get(k, '')) for k in ('statement', 'tags', 'id')))
        matches = sorted(query_words & text)
        path_matches = sorted(query_words & evidence)
        scope_matches = sorted(query_words & scope)
        graph_matches = sorted(related & (scope | evidence))
        reasons = []
        from .freshness import recency
        recent = recency(record)
        score = _TYPE.get(record.get('type'), 0) + recent
        reasons.append('recency: ' + str(round(recent, 2)))
        for label, hits, weight in [('text', matches, 100), ('evidence', path_matches, 180),
                                    ('scope', scope_matches, 140), ('architecture-neighbor', graph_matches, 45)]:
            if hits:
                reasons.append(label + ': ' + ', '.join(hits))
                score += min(len(hits), 8) * weight
        if record.get('state') in {'stale', 'inferred', 'unknown'}:
            reasons.append('review-state: ' + record['state'])
            score -= 5
        relevant = bool(matches or path_matches or scope_matches or graph_matches)
        essential = record.get('type') == 'constraint' or (record.get('type') in {'handoff', 'next_action'} and record.get('state') != 'stale')
        if essential:
            reasons.append('essential: ' + str(record.get('type')))
        fallback = record.get('origin') == 'scanner' and record.get('scope') in {'project', 'project/stack', 'project/commands'}
        if fallback:
            reasons.append('project-bootstrap')
        result.append({'record': record, 'score': score, 'reasons': reasons,
                       'relevant': relevant, 'essential': essential, 'bootstrap': fallback})
    return sorted(result, key=lambda item: (-int(item['essential']), item['record'].get('state') == 'stale', -item['score'], item['record']['id']))


def search(root: Path, query: str) -> list[dict]:
    ranked = rank_records(root, visible_records(root), query)
    return [{**r['record'], 'retrieval': {'score': r['score'], 'reasons': r['reasons']}}
            for r in ranked if r['relevant']]


def read_records(root: Path, *, record_id: str | None = None,
                 component: str | None = None, limit: int = 20) -> dict:
    if bool(record_id) == bool(component):
        raise ValueError('Specify exactly one record ID or component')
    if not 1 <= limit <= 100:
        raise ValueError('limit must be between 1 and 100')
    records = visible_records(root)
    if record_id:
        matches = [r for r in records if r['id'] == record_id]
        if not matches:
            raise ValueError('Record unavailable')
    else:
        matches = [r for r in records if _component_matches(r, str(component))]
    return {'records': matches[:limit], 'total': len(matches), 'truncated': len(matches) > limit}
