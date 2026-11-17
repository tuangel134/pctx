"""Record revisions committed atomically with their canonical current value."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from .model import utc_now
from .security import secret_matches

HISTORY_FIELD = '_pctx_history'


def payload(record: dict) -> dict:
    return copy.deepcopy({k: v for k, v in record.items() if k != HISTORY_FIELD})


def content_digest(record: dict) -> str:
    data = {k: v for k, v in record.items() if k not in {HISTORY_FIELD, 'created_at', 'updated_at'}}
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_history(record: dict) -> list[dict]:
    history = record.get(HISTORY_FIELD)
    if history is None:
        return []  # Legacy records remain readable; first change preserves their baseline.
    if not isinstance(history, dict) or history.get('schema_version') != 1:
        raise ValueError('Unsupported record history schema')
    revisions = history.get('revisions')
    if not isinstance(revisions, list) or not revisions:
        raise ValueError('Record history must contain revisions')
    for number, revision in enumerate(revisions, 1):
        if not isinstance(revision, dict) or revision.get('revision') != number:
            raise ValueError('Record history sequence is corrupt')
        snapshot = revision.get('record')
        if not isinstance(snapshot, dict) or HISTORY_FIELD in snapshot or snapshot.get('id') != record.get('id'):
            raise ValueError('Record history identity is corrupt')
        if revision.get('digest') != content_digest(snapshot):
            raise ValueError('Record history digest mismatch')
        if record.get('sensitivity') not in {'private', 'secret'} and snapshot.get('sensitivity') in {'private', 'secret'}:
            raise ValueError('Public history contains a private revision')
    if revisions[-1]['digest'] != content_digest(record):
        raise ValueError('Current record and history differ; repair before writing')
    return revisions


def advance_history(existing: dict | None, current: dict) -> dict:
    revisions = copy.deepcopy(validate_history(existing)) if existing else []
    if existing and not revisions:
        revisions.append({'revision': 1, 'recorded_at': existing.get('updated_at', utc_now()),
                          'digest': content_digest(existing), 'record': payload(existing)})
    revisions.append({'revision': len(revisions) + 1, 'recorded_at': utc_now(),
                      'digest': content_digest(current), 'record': payload(current)})
    return {'schema_version': 1, 'revisions': revisions}


def _public_record(root: Path, record_id: str) -> dict:
    from .storage import load_records
    matches = [r for r in load_records(root) if r['id'] == record_id
               and r.get('sensitivity') not in {'private', 'secret'}]
    if not matches or secret_matches(json.dumps(matches[0], ensure_ascii=False)):
        raise ValueError('Record unavailable')
    return matches[0]


def record_history(root: Path, record_id: str, revision: int | None = None,
                   compare: int | None = None) -> dict:
    record = _public_record(root, record_id)
    revisions = validate_history(record)
    if not revisions:
        return {'id': record_id, 'legacy': True, 'current_revision': 0, 'revisions': []}
    result = {'id': record_id, 'legacy': False, 'current_revision': len(revisions),
              'revisions': [{k: v for k, v in r.items() if k != 'record'} | {
                  'origin': r['record'].get('origin'), 'state': r['record'].get('state')}
                  for r in revisions]}
    if compare is not None and revision is None:
        raise ValueError('A base revision is required for comparison')

    def snapshot(number: int) -> dict:
        if not 1 <= number <= len(revisions):
            raise ValueError('Revision unavailable')
        return copy.deepcopy(revisions[number - 1]['record'])

    if revision is not None:
        result['record'] = snapshot(revision)
    if compare is not None:
        before, after = result['record'], snapshot(compare)
        result['changes'] = {k: {'before': before.get(k), 'after': after.get(k)} for k in sorted(before.keys() | after.keys())
                             if k not in {'created_at', 'updated_at'} and before.get(k) != after.get(k)}
    return result


def restore_record(root: Path, record_id: str, revision: int, expected_revision: int) -> dict:
    from .storage import project_lock, upsert_record
    with project_lock(root):
        current = _public_record(root, record_id)
        if current.get('origin') == 'scanner' or record_id.startswith(('coord.', 'plan.', 'work.', 'fact.project.', 'procedure.project.')):
            raise ValueError('Scanner and work records are managed by PCTX')
        history = record_history(root, record_id, revision)
        if expected_revision != history['current_revision']:
            raise ValueError('Record changed; inspect current history before restoring')
        if 'record' not in history:
            raise ValueError('Legacy record has no restorable revision')
        restored = history['record']
        restored.update(origin='restore', state='inferred', restored_from=revision,
                        stale_reason='Historical revision restored; review current evidence.')
        return payload(upsert_record(root, restored))
