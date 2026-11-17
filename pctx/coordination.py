"""Cooperative, expiring reservations in canonical JSON; no model or daemon needed."""
from __future__ import annotations
import copy
import math
from pathlib import Path, PurePosixPath
import re
import time
import uuid

from .history import payload, validate_history
from .model import make_record
from .security import secret_matches
from .storage import load_records, project_lock, upsert_record

DEFAULT_TTL = 900
MAX_TTL = 3600


def _text(value, name, maximum=160, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()) or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid ' + name)
    if secret_matches(value):
        raise ValueError('Probable secret in ' + name)
    return value.strip()


def validate_lease(value):
    required = {'schema_version', 'session_id', 'task_id', 'paths', 'state', 'started_at', 'renewed_at', 'expires_at', 'ttl', 'summary'}
    if not isinstance(value, dict) or set(value) - {'release_reason'} != required or value['schema_version'] != 1:
        raise ValueError('Unsupported coordination lease schema')
    if value.get('release_reason') not in {None, 'expired', 'released'}:
        raise ValueError('Invalid release reason')
    _text(value['session_id'], 'session_id')
    if not isinstance(value['task_id'], str) or not re.fullmatch(r'plan\.[A-Za-z0-9_-]{1,100}', value['task_id']):
        raise ValueError('Lease requires a checklist task ID')
    paths = value['paths']
    if not isinstance(paths, list) or not 1 <= len(paths) <= 32 or any(not isinstance(p, str) for p in paths) or len(set(paths)) != len(paths):
        raise ValueError('Lease requires 1 to 32 unique paths')
    for path in paths:
        _path_syntax(path)
    if value['state'] not in {'held', 'released'}:
        raise ValueError('Invalid lease state')
    _ttl(value['ttl'])
    for key in ['started_at', 'renewed_at', 'expires_at']:
        t = value[key]
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0:
            raise ValueError('Invalid lease timestamp')
    if value['renewed_at'] < value['started_at'] or value['expires_at'] != value['renewed_at'] + value['ttl']:
        raise ValueError('Invalid lease interval')
    _text(value['summary'], 'summary', 500, empty=True)


def _ttl(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 60 <= value <= MAX_TTL:
        raise ValueError('ttl must be between 60 and 3600 seconds')
    return value


def _path_syntax(value):
    from .public_paths import syntax
    return syntax(value)


def _paths(root, paths):
    if not isinstance(paths, list) or not 1 <= len(paths) <= 32:
        raise ValueError('Lease requires 1 to 32 paths')
    result = []
    for name in paths:
        name = _path_syntax(name)
        cursor = root
        for part in name.split('/'):
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError('Symlink reservation unavailable')
            if cursor.is_file() and cursor.stat().st_nlink > 1:
                raise ValueError('Hard-linked reservation unavailable')
        if not cursor.resolve().is_relative_to(root.resolve()):
            raise ValueError('Reservation escapes project')
        result.append(name)
    if len(set(result)) != len(result):
        raise ValueError('Duplicate reservation paths')
    return sorted(result)


def _status(lease, now):
    if lease['state'] == 'released':
        return 'expired' if lease.get('release_reason') == 'expired' else 'released'
    # Fail closed if the coordinator's wall clock moves backwards.
    if now < lease['renewed_at']:
        return 'clock_anomaly'
    return 'active' if now < lease['expires_at'] else 'expired'


def _records(root):
    records = []
    for record in load_records(root):
        if 'coordination' not in record:
            continue
        if record.get('sensitivity') in {'private', 'secret'} or record.get('state') == 'superseded':
            raise ValueError('Coordination record must remain public/internal and active')
        previous = None
        history = validate_history(record)
        if not history:
            raise ValueError('Coordination history is required')
        for revision in history:
            lease = revision['record'].get('coordination')
            validate_lease(lease)
            if previous is not None:
                if any(lease[k] != previous[k] for k in ('session_id', 'task_id', 'paths', 'started_at')) or (previous['state'] == 'released' and lease != previous) or lease['renewed_at'] < previous['renewed_at']:
                    raise ValueError('Coordination history identity or lifecycle changed')
            previous = lease
        records.append(record)
    return records


def _row(record, now):
    lease = copy.deepcopy(record['coordination'])
    return lease | {'id': record['id'], 'status': _status(lease, now), 'current_revision': len(validate_history(record)), 'remaining_seconds': max(0, math.ceil(lease['expires_at'] - now)) if lease['state'] == 'held' else 0}


def active(root, now=None):
    now = time.time() if now is None else now
    return [_row(r, now) for r in _records(root) if _status(r['coordination'], now) in {'active', 'clock_anomaly'}]


def _overlap(a, b):
    # Conservative case-insensitive comparison also protects shared Windows trees.
    a, b = a.casefold(), b.casefold()
    return a == b or a.startswith(b + '/') or b.startswith(a + '/')


def _related(task, other, records):
    def ancestor(a, b):
        seen = set()
        while b in records and b not in seen:
            if a == b:
                return True
            seen.add(b)
            b = records[b]['checklist']['parent']
        return False
    return ancestor(task, other) or ancestor(other, task)


def for_task(root, task, records, leases=None):
    leases = active(root) if leases is None else leases
    return [r for r in leases if _related(task, r['task_id'], records)]


def guard(root, task, records, session_id=None, lease_id=None):
    claims = for_task(root, task, records)
    if not claims:
        if lease_id is not None:
            raise ValueError('Reservation expired or unavailable; stop editing and acquire again')
        return
    if len(claims) != 1 or claims[0]['status'] != 'active' or claims[0]['id'] != lease_id or claims[0]['session_id'] != session_id:
        raise ValueError('Task is reserved; supply its active lease_id and session_id')


def query(root: Path, action='list', *, id=None, session_id=None, status=None, offset=0, limit=20, budget=2000):
    from .planning import _bounded
    if action not in {'list', 'detail', 'history'}:
        raise ValueError('Unknown coordination read action')
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 100000 or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError('Invalid coordination pagination')
    if status is not None and status not in {'active', 'expired', 'released', 'clock_anomaly'}:
        raise ValueError('Invalid coordination status')
    now = time.time()
    records = _records(root)
    base = {'action': action, 'as_of': now, 'offset': offset, 'truncated': False, 'warning': 'Cooperative reservations in this shared root only. Recheck before editing. Expired holders must stop and reacquire. Session IDs are labels, not authentication.'}
    if action in {'detail', 'history'}:
        record = next((r for r in records if r['id'] == id), None)
        if record is None:
            raise ValueError('Reservation unavailable')
        if action == 'detail':
            return _bounded(base | {'detail': _row(record, now)}, budget)
        rows = [{'revision': rev['revision'], 'at': rev['recorded_at'], **rev['record']['coordination']} for rev in reversed(validate_history(record))]
    else:
        rows = [_row(r, now) for r in records]
        rows = [r for r in rows if (session_id is None or r['session_id'] == session_id) and (status is None or r['status'] == status)]
        rows.sort(key=lambda r: (r['status'] not in {'active', 'clock_anomaly'}, -r['started_at'], r['id']))
    page = rows[offset:offset + limit]
    return _bounded(base | {'items': page, 'total': len(rows), 'next_offset': offset + len(page) if offset + len(page) < len(rows) else None, 'truncated': offset + len(page) < len(rows)}, budget)


def update(root: Path, action, *, session_id=None, id=None, task_id=None, paths=None, ttl=None, expected_revision=None, summary=None):
    from .planning import _records as plans, _views
    if action == 'cleanup':
        return cleanup(root)
    if action not in {'claim', 'renew', 'release'}:
        raise ValueError('Unknown coordination write action')
    session_id = _text(session_id, 'session_id')
    requested_ttl = None if ttl is None else _ttl(ttl)
    if summary is not None:
        summary = _text(summary, 'summary', 500, empty=action != 'release')
    if action == 'renew' and not summary:
        summary = None  # An empty heartbeat must not erase the last useful checkpoint.
    if action == 'release' and not summary:
        raise ValueError('Release requires a short handoff summary')
    with project_lock(root):
        now = time.time()
        records = _records(root)
        if action == 'claim':
            _cleanup(root, records, now)
            records = _records(root)
            if id is not None or expected_revision is not None:
                raise ValueError('New claims receive a fresh lease ID')
            ttl = DEFAULT_TTL if requested_ttl is None else requested_ttl
            paths = _paths(root, paths)
            tasks = plans(root)
            if task_id not in tasks:
                aliases = [rid for rid in tasks if isinstance(task_id,str) and re.split(r'[._-]',rid.casefold())[-1] == task_id.casefold()]
                if len(aliases) == 1: task_id = aliases[0]
                else:
                    from .storage import load_manifest
                    raise ValueError('Checklist task unavailable or ambiguous in '+load_manifest(root)['name']+'; inspect pctx plan list using this same --root and use its full ID')
            views = _views(root, tasks)
            view = views[task_id]
            if view['status'] not in {'pending', 'needs_review', 'in_progress'}:
                raise ValueError('Task is closed or blocked')
            if view['owner'] and view['owner'] != session_id:
                raise ValueError('Task is assigned to another owner')
            if any(views[dep]['status'] not in {'done', 'verified'} for dep in view['dependencies']):
                raise ValueError('Task has unfinished dependencies')
            claims = [_row(r, now) for r in records if _status(r['coordination'], now) in {'active', 'clock_anomaly'}]
            conflicts = [r for r in claims if _related(task_id, r['task_id'], tasks) or any(_overlap(a, b) for a in paths for b in r['paths'])]
            if conflicts:
                raise ValueError('Reservation conflict; inspect pctx_coordination active. Held by: ' + ', '.join(r['id'] for r in conflicts[:5]))
            lease = {'schema_version': 1, 'session_id': session_id, 'task_id': task_id, 'paths': paths, 'state': 'held', 'started_at': now, 'renewed_at': now, 'expires_at': now + ttl, 'ttl': ttl, 'summary': summary or ''}
            id = 'coord.' + uuid.uuid4().hex
            record = make_record(record_type='note', record_id=id, statement='Cooperative reservation; query pctx_coordination for live validity.', origin='coordination', state='inferred', stability='volatile', coordination=lease)
        else:
            existing = next((r for r in records if r['id'] == id), None)
            if existing is None:
                raise ValueError('Reservation unavailable')
            lease = existing['coordination']
            if lease['session_id'] != session_id:
                raise ValueError('Reservation belongs to another session')
            if action=='release' and lease['state']=='released' and lease.get('release_reason')=='expired':
                return _row(existing,now) | {'already_released':True,'summary_saved':False,'warning':'Expired reservation was already cleaned; submit any late checkpoint with pctx report.'}
            revision = len(validate_history(existing))
            if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision != revision:
                raise ValueError('Reservation revision changed; inspect before updating')
            if lease['state'] == 'released':
                raise ValueError('Reservation already released')
            if task_id is not None or paths is not None:
                raise ValueError('Reservation scope is immutable; release and claim a new scope')
            record = payload(existing)
            lease = record['coordination']
            if action == 'renew':
                if _status(lease, now) != 'active':
                    raise ValueError('Reservation expired or clock changed; stop editing and acquire again')
                _paths(root, lease['paths'])
                if revision >= 512:
                    raise ValueError('Reservation history limit; checkpoint, release and claim again')
                ttl = lease['ttl'] if requested_ttl is None else requested_ttl
                lease.update(renewed_at=now, expires_at=now + ttl, ttl=ttl)
            else:
                lease['state'] = 'released'
                lease['release_reason'] = 'released'
            if summary is not None:
                lease['summary'] = summary
        validate_lease(lease)
        saved = upsert_record(root, record)
        # Dynamic occupancy is deliberately NOT written into checklist revisions or indexes.
        from .tasks import ensure_tasks_file
        from .compile import export_context
        ensure_tasks_file(root)
        export_context(root)
        return _row(saved, now)


def brief(root, limit=4):
    claims = active(root)
    if not claims:
        return ''
    lines = [f'Coordination: {len(claims)} active reservations (check live expiry with pctx_coordination).']
    for r in claims[:limit]:
        lines.append(f"- {r['task_id']} reserved by {r['session_id'][:80]}: {', '.join(r['paths'])[:180]}; expires_at={r['expires_at']}; {r['id']}")
    lines.append(f'Coverage: {min(limit, len(claims))}/{len(claims)}. Shared-root cooperative protocol; claim before edits, renew, checkpoint and release. Expired sessions must stop.')
    return '\n'.join(lines)


def _cleanup(root, records, now):
    released=[]
    for record in records:
        lease=record['coordination']
        if lease['state']=='held' and now>=lease['expires_at']:
            value=payload(record)
            value['coordination'].update(state='released',release_reason='expired')
            saved=upsert_record(root,value);released.append(saved['id'])
    return released


def cleanup(root):
    with project_lock(root):
        released=_cleanup(root,_records(root),time.time())
        return {'expired_released':len(released),'ids':released,'warning':'Checkpoints/history retained; expired workers must stop and claim again.'}
