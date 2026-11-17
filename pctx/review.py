"""Evidence inspection and explicit review of durable public knowledge."""
from __future__ import annotations

from collections import defaultdict
import copy
import json
from pathlib import Path
import re
import unicodedata

from .history import payload, record_history, validate_history
from .model import utc_now
from .retrieval import visible_records, words
from .security import secret_matches
from .storage import load_records, project_lock, safe_relative, sha256_file, upsert_record


def evidence_status(root: Path, record: dict, cache: dict | None = None) -> list[dict]:
    from .freshness import evidence_status as inspect
    return inspect(root, record.get('evidence', []), cache)


def _normalized(text: str) -> str:
    text = ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))
    return ' '.join(re.findall(r'[^\W_]+', text, flags=re.UNICODE))


def _candidates(records: list[dict], max_pairs: int = 2000) -> tuple[list[dict], bool]:
    duplicates, keyed, scoped = defaultdict(list), defaultdict(list), defaultdict(list)
    for record in records:
        key = (record['scope'], record['type'])
        statement = _normalized(record['statement'])
        if statement:
            duplicates[key + (statement,)].append(record['id'])
        if record.get('claim_key'):
            keyed[(record['scope'], str(record['claim_key']))].append(record)
        scoped[key].append(record)
    found = []
    duplicate_pairs = set()
    for ids in duplicates.values():
        if len(ids) > 1:
            found.append({'kind': 'duplicate-candidate', 'ids': sorted(ids), 'reason': 'Same scope, type and normalized statement'})
            duplicate_pairs.update(tuple(sorted((ids[0], item))) for item in ids[1:])
    for items in keyed.values():
        if len({_normalized(r['statement']) for r in items}) > 1:
            found.append({'kind': 'conflict-candidate', 'ids': sorted(r['id'] for r in items), 'reason': 'Same explicit claim_key with different statements'})
    compared, truncated = 0, False
    for key in sorted(scoped):
        group = sorted(scoped[key], key=lambda r: r['id'])
        tokenized = {r['id']: words(r['statement']) for r in group}
        for i, left in enumerate(group):
            for right in group[i + 1:]:
                if compared >= max_pairs:
                    truncated = True
                    break
                compared += 1
                pair = (left['id'], right['id'])
                a, b = tokenized[left['id']], tokenized[right['id']]
                common, union = a & b, a | b
                if pair not in duplicate_pairs and a != b and len(common) >= 2 and len(common) / max(1, len(union)) >= 0.5:
                    found.append({'kind': 'difference-candidate', 'ids': list(pair),
                                  'reason': 'Related wording in the same scope; this is not proof of contradiction'})
            if truncated:
                break
        if truncated:
            break
    return sorted(found, key=lambda c: (c['kind'], c['ids'])), truncated


def review_queue(root: Path, *, offset: int = 0, limit: int = 50) -> dict:
    if offset < 0 or not 1 <= limit <= 500:
        raise ValueError('offset must be nonnegative and limit between 1 and 500')
    raw = load_records(root)
    revisions = {r['id']: len(validate_history(r)) for r in raw}
    records = [payload(r) for r in raw if r.get('state') != 'superseded' and 'checklist' not in r and 'coordination' not in r
               and r.get('sensitivity') not in {'private', 'secret'}
               and not secret_matches(json.dumps(r, ensure_ascii=False))]
    from .freshness import project
    records = project(root, records)
    candidates, truncated = _candidates(records)
    affected = defaultdict(set)
    for candidate in candidates:
        for rid in candidate['ids']:
            affected[rid].add(candidate['kind'])
    rows, cache = [], {}
    for record in records:
        evidence = evidence_status(root, record, cache)
        reasons = set(affected[record['id']])
        if record['state'] in {'inferred', 'unknown', 'stale'}:
            reasons.add('state:' + record['state'])
        reasons.update('evidence:' + e['status'] for e in evidence if e['status'] != 'current')
        if reasons:
            rows.append({'id': record['id'], 'state': record['state'], 'statement': record['statement'],
                         'reasons': sorted(reasons), 'evidence': evidence,
                         'current_revision': revisions[record['id']]})
    page = rows[offset:offset + limit]
    page_ids = {r['id'] for r in page}
    page_candidates = [c for c in candidates if page_ids.intersection(c['ids'])]
    return {'records': page, 'total': len(rows), 'offset': offset, 'limit': limit,
            'truncated': offset + limit < len(rows), 'candidate_analysis_truncated': truncated,
            'candidates': page_candidates[:limit],
            'candidates_truncated': len(page_candidates) > limit, 'candidate_count': len(candidates),
            'warning': 'Candidates require review; no contradiction or resolution is inferred automatically.'}


def review_record(root: Path, record_id: str, action: str, *, expected_revision: int,
                  statement: str | None = None, replacement_id: str | None = None,
                  actor: str = 'mcp') -> dict:
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
        raise ValueError('Inspect the current revision before reviewing')
    if action not in {'confirm', 'correct', 'supersede'}:
        raise ValueError('Review action must be confirm, correct or supersede')
    if action == 'confirm' and actor != 'user':
        raise ValueError('Human confirmation is available through CLI or the dashboard; MCP corrections remain inferred')
    with project_lock(root):
        records = {payload(r)['id']: payload(r) for r in load_records(root) if r.get('sensitivity') not in {'private', 'secret'} and not secret_matches(json.dumps(r, ensure_ascii=False))}
        if record_id not in records:
            raise ValueError('Record unavailable')
        record = copy.deepcopy(records[record_id])
        if record.get('origin') == 'scanner' or record_id.startswith(('coord.', 'plan.', 'work.', 'fact.project.', 'procedure.project.')):
            raise ValueError('Scanner and work records are managed by PCTX')
        if record_history(root, record_id)['current_revision'] != expected_revision:
            raise ValueError('Record changed; inspect it before reviewing')
        if action == 'confirm':
            checked = evidence_status(root, record)
            if any(e['status'] in {'missing', 'unsafe', 'unreadable', 'not-file', 'ref-advanced', 'git-unavailable', 'workspace-changed'} for e in checked):
                raise ValueError('Evidence is unavailable or unsafe; correct the references before confirming')
            hashes = {e['path']: e['current_hash'] for e in checked if 'path' in e and 'current_hash' in e}
            for item in record['evidence']:
                if item.get('path') in hashes:
                    item['content_hash'] = hashes[item['path']]
            record.update(state='user_asserted', reviewed_at=utc_now(), reviewed_by='user')
            record.pop('stale_reason', None)
            record.pop('stale_at', None)
        elif action == 'correct':
            if not statement or not statement.strip():
                raise ValueError('A correction requires a nonempty statement')
            record.update(statement=statement.strip(), state='inferred', origin=actor,
                          reviewed_at=utc_now(), reviewed_by=actor)
        else:
            if not replacement_id or replacement_id == record_id or replacement_id not in records:
                raise ValueError('Choose a different available replacement record')
            # One durable link identifies both records; its inverse is derived.
            # This avoids a two-file transaction and leaves the replacement untouched.
            record.update(state='superseded', superseded_by=replacement_id,
                          reviewed_at=utc_now(), reviewed_by=actor)
        if secret_matches(json.dumps(record, ensure_ascii=False)):
            raise ValueError('Review would persist a probable secret')
        return payload(upsert_record(root, record))
