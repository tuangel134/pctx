"""Goals and checklists in canonical JSON records, with bounded AI views."""
from __future__ import annotations
import copy
from collections import deque
import hashlib
import json
from pathlib import Path
import re
import uuid

from .history import payload, validate_history
from .model import make_record, utc_now
from .planning_model import STATUSES, DIFFICULTIES, RISKS, PRIORITIES, OUTCOMES, LABELS, KINDS, validate_checklist, audit_checklist_history
from .security import secret_matches
from .storage import load_records, project_lock, safe_relative, sha256_file, upsert_record


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _records(root):
    records = {r['id']: r for r in load_records(root) if 'checklist' in r and r.get('state') != 'superseded' and r.get('sensitivity') not in {'private', 'secret'} and not secret_matches(json.dumps(r, ensure_ascii=False))}
    for record in records.values():
        audit_checklist_history(record, validate_history(record))
    return records


def _definition(item):
    return _digest({k: v for k, v in item.items() if k not in {'status', 'reason', 'owner', 'review_count', 'last_review'}})


def _proof(root, paths):
    if not isinstance(paths, list) or len(paths) > 30:
        raise ValueError('Evidence must contain at most 30 paths')
    evidence = []
    for relative in dict.fromkeys(paths):
        if not isinstance(relative, str) or not relative or len(relative) > 500:
            raise ValueError('Invalid evidence path')
        if relative.startswith('git:'):
            from .freshness import git_evidence
            evidence.append(git_evidence(root, relative[4:])); continue
        name = Path(relative)
        if name.is_absolute() or any(p.startswith('.') for p in name.parts) or any(re.search(r'(?i)(secret|credential|token|password|auth\.json)', p) for p in name.parts) or name.suffix.lower() in {'.key', '.pem', '.p12', '.pfx'}:
            raise ValueError('Evidence must be a public project file')
        cursor = root
        for part in name.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError('Symlink evidence is unavailable')
        path = safe_relative(root, relative)
        if not path.is_file():
            raise ValueError('Evidence file unavailable')
        evidence.append({'path': name.as_posix(), 'content_hash': sha256_file(path)})
    return evidence


def _graph(records, *, ordered=False):
    children = {rid: [] for rid in records}
    for rid, record in records.items():
        p = record['checklist']['parent']
        if p:
            if p not in records:
                raise ValueError('Checklist parent unavailable')
            children[p].append(rid)
    edges = {}
    for rid, record in records.items():
        deps = record['checklist']['dependencies']
        if any(dep not in records for dep in deps):
            raise ValueError('Checklist dependency unavailable')
        edges[rid] = children[rid] + deps
    # Dependency-first order without Python recursion, even for very large plans.
    waiting = {rid: len(set(targets)) for rid, targets in edges.items()}
    dependents = {rid: [] for rid in records}
    for rid, targets in edges.items():
        for target in set(targets):
            dependents[target].append(rid)
    queue = deque(rid for rid in records if waiting[rid] == 0)
    order = []
    while queue:
        rid = queue.popleft()
        order.append(rid)
        for dependent in dependents[rid]:
            waiting[dependent] -= 1
            if waiting[dependent] == 0:
                queue.append(dependent)
    if len(order) != len(records):
        raise ValueError('Checklist dependency or hierarchy cycle')
    for rid in records:
        cur, depth = rid, 0
        while records[cur]['checklist']['parent']:
            depth += 1
            cur = records[cur]['checklist']['parent']
            if depth > 8:
                raise ValueError('Checklist hierarchy is limited to eight levels')
    return (children, order) if ordered else children


def _views(root, records):
    children, order = _graph(records, ordered=True)
    from .coordination import active, for_task
    leases = active(root)
    views, proofs = {}, {}
    revisions = {rid: len(validate_history(record)) for rid, record in records.items()}
    def view(rid):
        if rid in views:
            return views[rid]
        record = records[rid]
        item = copy.deepcopy(record['checklist'])
        subs = [views[x] for x in children[rid]]
        deps = [views[x] for x in item['dependencies']]
        reasons = []
        if item['status'] in {'done', 'verified'}:
            if any(x['status'] not in {'done', 'verified', 'cancelled'} for x in subs):
                reasons.append('unfinished children')
            if any(x['status'] not in {'done', 'verified'} for x in deps):
                reasons.append('unfinished dependencies')
        review = item['last_review']
        review_current = bool(review and review['outcome'] == 'passed' and review.get('definition_hash') == _definition(item) and review['evidence'])
        evidence = []
        if review:
            for e in review['evidence']:
                if e.get('kind') == 'git':
                    from .freshness import evidence_status
                    checked = evidence_status(root, [e], proofs)[0]
                    current = checked['status'] == 'current'
                    evidence.append(e | {'status':'current' if current else 'changed_or_unavailable'})
                    review_current = review_current and current
                    continue
                path = e.get('path')
                if path not in proofs:
                    try:
                        proofs[path] = _proof(root, [path])[0]['content_hash']
                    except (ValueError, OSError):
                        proofs[path] = None
                current = proofs[path] == e.get('content_hash') and proofs[path] is not None
                evidence.append(e | {'status': 'current' if current else 'changed_or_unavailable'})
                review_current = review_current and current
            related = children[rid] + item['dependencies']
            review_current = review_current and review.get('related_revisions', {}) == {x: revisions[x] for x in related}
        review_valid = bool(review_current and item['criteria'] and {c['id'] for c in item['criteria']}.issubset(review['criteria']))
        if item['status'] == 'verified':
            if not review_valid:
                reasons.append('review missing, incomplete or outdated')
            if any(x['status'] not in {'verified', 'cancelled'} for x in subs) or any(x['status'] != 'verified' for x in deps):
                reasons.append('children or dependencies not verified')
        status = 'needs_review' if reasons else item['status']
        reservations = for_task(root, rid, records, leases)
        row = item | {'reservations': [{k: r[k] for k in ('id', 'session_id', 'task_id', 'expires_at', 'status')} for r in reservations], 'working': bool(reservations), 'id': rid, 'declared_status': item['status'], 'status': status,
                      'current_revision': revisions[rid], 'children': children[rid],
                      'current_passed_criteria': list(review['criteria']) if review_current else [],
                      'review_valid': bool(review_valid), 'evidence': evidence, 'warnings': reasons,
                      'difficulty_label': LABELS[item['difficulty']],
                      'progress': {s: sum(x['status'] == s for x in subs) for s in STATUSES},
                      'ready': not reservations and not children[rid] and status in {'pending', 'needs_review'} and not item['owner'] and all(x['status'] in {'done', 'verified'} for x in deps),
                      'review_guidance': 'Demand an independent security/data review' if item['risk'] == 'high' else 'Match reviewer capability to difficulty and acceptance criteria'}
        views[rid] = row
        return row
    for rid in order:
        view(rid)
    return views


def _brief(row):
    return {k: row[k] for k in ('id', 'title', 'kind', 'parent', 'status', 'priority', 'owner', 'difficulty', 'risk', 'ready', 'review_count', 'current_revision', 'working', 'reservations')} | {'children': len(row['children']), 'progress': row['progress'], 'last_outcome': (row['last_review'] or {}).get('outcome')}


def _bounded(result, budget):
    if isinstance(budget, bool) or not isinstance(budget, int) or not 256 <= budget <= 100000:
        raise ValueError('budget must be between 256 and 100000 tokens (character estimate)')
    result['budget'] = budget
    result['tokens_estimate'] = 0
    while True:
        wire = json.dumps(result, ensure_ascii=False, separators=(',', ':'))
        estimate = (len(wire) + 3) // 4
        if estimate <= budget:
            result['tokens_estimate'] = estimate
            # Include the estimate itself in the estimate.
            result['tokens_estimate'] = (len(json.dumps(result, ensure_ascii=False, separators=(',', ':'))) + 3) // 4
            if result['tokens_estimate'] <= budget:
                return result
        if result.get('items'):
            result['items'].pop()
            result['truncated'] = True
            result['next_offset'] = result.get('offset', 0) + len(result['items'])
        elif 'detail' in result:
            result.pop('detail')
            result.update(truncated=True, warning='Detail exceeds budget; increase budget. No detail was returned.')
        else:
            raise ValueError('Budget is too small for response metadata')


def query(root: Path, action='summary', *, id=None, parent=None, goal=None, status=None, kind=None, difficulty=None, risk=None, ready=None, offset=0, limit=20, budget=2000):
    if action not in {'summary', 'list', 'detail', 'history'}:
        raise ValueError('Unknown plan read action')
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 100000 or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError('Invalid checklist pagination')
    for field, value, options in [('status', status, STATUSES), ('kind', kind, KINDS), ('difficulty', difficulty, DIFFICULTIES), ('risk', risk, RISKS)]:
        if value is not None and value not in options:
            raise ValueError('Invalid ' + field + ' filter')
    if ready is not None and not isinstance(ready, bool):
        raise ValueError('ready must be boolean')
    records = _records(root)
    if action in {'detail', 'history'} and id not in records:
        raise ValueError('Checklist item unavailable')
    views = _views(root, records)
    base = {'action': action, 'offset': offset, 'truncated': False}
    if action == 'detail':
        return _bounded(base | {'detail': views[id]}, budget)
    if action == 'history':
        seen, events = set(), []
        for rev in validate_history(records[id]):
            item = rev['record']['checklist']
            review = item['last_review']
            event = {'revision': rev['revision'], 'at': rev['recorded_at'], 'status': item['status'], 'review': None}
            if review and review['id'] not in seen:
                event['review'] = review
                seen.add(review['id'])
            events.append(event)
        events.reverse()
        rows = events
    else:
        rows = list(views.values())
        if goal is not None:
            if goal not in views:
                raise ValueError('Goal unavailable')
            def belongs(row):
                cur = row['id']
                while cur:
                    if cur == goal:
                        return True
                    cur = views[cur]['parent']
                return False
            rows = [r for r in rows if belongs(r)]
        rows = [r for r in rows if (parent is None or r['parent'] == (None if parent == 'root' else parent)) and all(value is None or r[field] == value for field, value in [('status', status), ('kind', kind), ('difficulty', difficulty), ('risk', risk), ('ready', ready)])]
        counts = {s: sum(r['status'] == s for r in rows) for s in STATUSES}
        levels = {d: sum(r['difficulty'] == d for r in rows) for d in DIFFICULTIES}
        base.update(counts=counts, difficulty_counts=levels, total_items=len(rows))
        if action == 'summary':
            base['warning'] = 'Done is declared completion. Verified requires current evidence. Review counts are recorded checks, not guaranteed independent audits. Difficulty is explicit, not model selection.'
            rows = [r for r in rows if r['parent'] is None]
        rows.sort(key=lambda r: (PRIORITIES.index(r['priority']) * -1, r['id']))
        rows = [_brief(r) for r in rows]
    page = rows[offset:offset + limit]
    return _bounded(base | {'items': page, 'total': len(rows), 'truncated': offset + len(page) < len(rows), 'next_offset': offset + len(page) if offset + len(page) < len(rows) else None}, budget)


def _criteria(texts):
    if not isinstance(texts, list):
        raise ValueError('criteria must be a list of strings')
    if any(not isinstance(x, str) for x in texts):
        raise ValueError('criteria must be strings')
    return [{'id': 'criterion.' + _digest(text.strip())[:12], 'text': text.strip()} for text in texts]


def update(root: Path, action: str, *, id=None, expected_revision=None, title=None, kind=None, description=None, parent=None, dependencies=None, priority=None, owner=None, criteria=None, difficulty=None, difficulty_reason=None, risk=None, status=None, reason=None, outcome=None, summary=None, reviewer=None, evidence=None, covered_criteria=None, event_id=None, session_id=None, lease_id=None):
    if action not in {'create', 'edit', 'status', 'review'}:
        raise ValueError('Unknown plan write action')
    with project_lock(root):
        records = _records(root)
        from .coordination import guard
        if action != 'create':
            guard(root, id, records, session_id, lease_id)
        if parent and parent != 'root':
            guard(root, parent, records, session_id, lease_id)
        if action == 'create':
            id = id or 'plan.' + uuid.uuid4().hex[:16]
            if not isinstance(id, str) or not re.fullmatch(r'plan\.[A-Za-z0-9_-]{1,100}', id):
                raise ValueError('Checklist IDs must use plan.NAME')
            if any(r['id'] == id for r in load_records(root)):
                raise ValueError('Checklist ID already exists; inspect it before editing')
            item = {'schema_version': 1, 'work_generation': 0, 'title': title, 'kind': kind or 'task', 'description': description or '', 'parent': parent, 'dependencies': dependencies or [], 'priority': priority or 'normal', 'owner': owner or '', 'criteria': _criteria(criteria or []), 'difficulty': difficulty or 'unknown', 'difficulty_reason': difficulty_reason or '', 'risk': risk or 'unknown', 'status': 'pending', 'reason': '', 'review_count': 0, 'last_review': None}
            record = make_record(record_type='note', record_id=id, statement=title or '', state='inferred', origin='planning', checklist=item)
        else:
            if id not in records:
                raise ValueError('Checklist item unavailable')
            record = payload(records[id])
            item = record['checklist']
            if action == 'review':
                if outcome not in OUTCOMES or not isinstance(summary, str) or not 1 <= len(summary.strip()) <= 2000 or not isinstance(reviewer, str) or not 1 <= len(reviewer.strip()) <= 160:
                    raise ValueError('Review requires outcome, summary and named reviewer')
                event_id = event_id or uuid.uuid4().hex
                if not isinstance(event_id, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,100}', event_id):
                    raise ValueError('Invalid review event ID')
                request_hash = _digest([outcome, summary, reviewer, evidence or [], covered_criteria or []])
                for revision in validate_history(records[id]):
                    prior = revision['record']['checklist']['last_review']
                    if prior and prior['id'] == event_id:
                        if prior['request_hash'] != request_hash:
                            raise ValueError('Review event ID was already used for another result')
                        return {'id': id, 'already_recorded': True, 'current_revision': len(validate_history(records[id]))}
            if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision != len(validate_history(records[id])):
                raise ValueError('Checklist changed; read its current revision before writing')
            if action == 'edit':
                for field, val in [('title', title), ('kind', kind), ('description', description), ('dependencies', dependencies), ('priority', priority), ('owner', owner), ('difficulty', difficulty), ('difficulty_reason', difficulty_reason), ('risk', risk)]:
                    if val is not None:
                        item[field] = val
                if parent is not None:
                    item['parent'] = None if parent == 'root' else parent
                if criteria is not None:
                    item['criteria'] = _criteria(criteria)
                if _definition(item) != _definition(records[id]['checklist']):
                    item['work_generation'] = item.get('work_generation', 0) + 1
                    if item['status'] == 'verified':
                        item['status'] = 'needs_review'
            elif action == 'status':
                if status not in STATUSES:
                    raise ValueError('Invalid checklist status')
                if status in {'blocked', 'cancelled'} and not reason:
                    raise ValueError('Blocked or cancelled work requires a reason')
                if status != item['status'] and status in {'pending', 'in_progress', 'needs_review', 'blocked'}:
                    item['work_generation'] = item.get('work_generation', 0) + 1
                item['status'] = status
                item['reason'] = reason or ''
            elif action == 'review':
                covered = covered_criteria or []
                if not isinstance(covered, list) or any(not isinstance(x, str) for x in covered) or len(covered) != len(set(covered)) or any(x not in {c['id'] for c in item['criteria']} for x in covered):
                    raise ValueError('Review refers to unavailable acceptance criteria')
                children = _graph(records)[id]
                item['last_review'] = {'id': event_id, 'at': utc_now(), 'outcome': outcome, 'summary': summary.strip(), 'reviewer': reviewer.strip(), 'criteria': covered, 'evidence': _proof(root, evidence or []), 'definition_hash': _definition(item), 'request_hash': request_hash, 'related_revisions': {x: len(validate_history(records[x])) for x in children + item['dependencies']}}
                item['review_count'] += 1
                record['state'] = 'inferred'  # Fresh explicit review replaces a stale evidence marker.
                record.pop('stale_reason', None)
                record.pop('stale_at', None)
                if outcome != 'passed':
                    item['status'] = 'blocked' if outcome == 'blocked' else 'needs_review'
                elif item['status'] == 'verified':
                    item['status'] = 'done'  # Explicit verification after every new review.
        validate_checklist(item)
        record['statement'] = f"Checklist {item['kind']}: {item['title']}. Declared status: {item['status']}. Difficulty: {item['difficulty']}; risk: {item['risk']}; recorded reviews: {item['review_count']}. Inspect pctx_plan for current validity."
        record['updated_at'] = utc_now()
        record['links'] = [{'relation': 'depends_on', 'target': 'record:' + x} for x in item['dependencies']]
        if item['parent']:
            record['links'].append({'relation': 'supports', 'target': 'record:' + item['parent']})
        record['evidence'] = copy.deepcopy((item['last_review'] or {}).get('evidence', []))
        candidate = records | {id: record}
        _graph(candidate)
        # Editing a completed parent cannot silently introduce open work/dependencies.
        views = _views(root, candidate)
        row = views[id]
        if action == 'status' and status in {'done', 'verified'} and row['warnings']:
            raise ValueError('Cannot close checklist: ' + '; '.join(row['warnings']))
        if action == 'status' and status == 'verified' and not row['review_valid']:
            raise ValueError('Verification requires a passed review covering all criteria with current evidence')
        saved = upsert_record(root, record)
        from .tasks import ensure_tasks_file
        from .compile import export_context
        ensure_tasks_file(root)
        export_context(root)
        return {'id': id, 'current_revision': len(validate_history(saved)), 'status': _views(root, _records(root))[id]['status'], 'review_count': item['review_count']}


def brief(root: Path, limit=8):
    views = _views(root, _records(root))
    from .coordination import brief as coordination_brief
    coordination = coordination_brief(root)
    if not views:
        return coordination
    counts = {s: sum(r['status'] == s for r in views.values()) for s in STATUSES}
    lines = ['## Goals and checklist overview', 'States: ' + ', '.join(f'{s}={n}' for s, n in counts.items() if n), 'Done is declared; verified requires current evidence. Difficulty is explicit; risk is separate.']
    roots = [r for r in views.values() if r['parent'] is None]
    leaves = [r for r in views.values() if not r['children'] and r['status'] not in {'done', 'verified', 'cancelled'}]
    ordered = roots + sorted(leaves, key=lambda r: (-PRIORITIES.index(r['priority']), r['id']))
    for r in ordered[:limit]:
        lines.append(f"- {r['id']}: {r['title'][:160]} [{r['status']}; {r['difficulty']}; risk={r['risk']}; ready={str(r['ready']).lower()}; reviews={r['review_count']}]")
    lines.append(f'Coverage: {min(limit, len(ordered))}/{len(ordered)} goals/open leaves shown. Use pctx_plan list with difficulty and ready filters; detail/history for criteria and checks. Never infer completed work was reviewed.')
    if coordination:
        lines.append(coordination)
    return '\n'.join(lines)


def markdown(root: Path):
    views = _views(root, _records(root))
    if not views:
        return ''
    lines = ['## Goals and checklists', 'A checked box means declared completion. Review outcome and current evidence are separate.']
    def emit(rid, depth):
        r = views[rid]
        pad = '  ' * depth
        lines.append(f"{pad}- [{'x' if r['status'] in {'done', 'verified'} else ' '}] {r['title']} (`{rid}`) — {r['status']}; {LABELS[r['difficulty']]}; risk={r['risk']}; reviews={r['review_count']}; latest={(r['last_review'] or {}).get('outcome', 'none')}")
        if r['reservations']:
            lines.append(f"{pad}  Working (recheck live expiry): " + ', '.join(f"{c['session_id']} until {c['expires_at']} ({c['id']})" for c in r['reservations']))
        if r['difficulty_reason']:
            lines.append(f"{pad}  Difficulty reason: {r['difficulty_reason']}")
        if r['dependencies']:
            lines.append(f"{pad}  Dependencies: {', '.join(r['dependencies'])}")
        for c in r['criteria']:
            lines.append(f"{pad}  - [{'x' if c['id'] in r['current_passed_criteria'] else ' '}] {c['text']} (`{c['id']}`)")
        if r['warnings']:
            lines.append(f"{pad}  Needs attention: {', '.join(r['warnings'])}")
        for child in r['children']:
            emit(child, depth + 1)
    for rid, r in views.items():
        if r['parent'] is None:
            emit(rid, 0)
    return '\n'.join(lines)
