"""Portable content snapshots; independent of rebuildable scanner caches."""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
from .history import content_digest
from .model import utc_now
from .retrieval import visible_records
from .scan import collect_files, git_snapshot
from .storage import load_manifest, sha256_file, safe_relative


def capture_snapshot(root: Path, *, max_files: int = 10000) -> dict:
    root = root.resolve()
    paths = collect_files(root, max_files=max_files + 1)
    files, errors = {}, []
    for path in paths[:max_files]:
        name = path.relative_to(root).as_posix()
        try:
            before = path.stat()
            digest = sha256_file(path)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                errors.append({'path': name, 'status': 'unstable'}); continue
            files[name] = digest
        except OSError:
            errors.append({'path': name, 'status': 'unreadable'})
    records = {r['id']: content_digest(r) for r in visible_records(root)
               if r.get('origin') != 'scanner' and not r['id'].startswith('work.')}
    git = git_snapshot(root)
    return {'schema_version': 1, 'project_id': load_manifest(root)['project_id'],
            'captured_at': utc_now(), 'files': files, 'records': records,
            'git': {k: git[k] for k in ('is_git', 'branch', 'head')},
            'truncated': len(paths) > max_files, 'errors': errors}


def _delta(old: dict, new: dict) -> dict:
    return {'added': sorted(new.keys() - old.keys()), 'removed': sorted(old.keys() - new.keys()),
            'modified': sorted(k for k in old.keys() & new.keys() if old[k] != new[k])}


def compare_snapshot(root: Path, saved: dict | None) -> dict:
    if not saved:
        return {'ok': False, 'complete': False, 'legacy': True,
                'warning': 'No content snapshot saved; workspace equality cannot be verified.', 'differences': ['snapshot-unavailable']}
    if not isinstance(saved, dict) or saved.get('schema_version') != 1:
        raise ValueError('Unsupported continuity snapshot schema')
    if saved.get('project_id') != load_manifest(root)['project_id']:
        raise ValueError('Snapshot belongs to a different project')
    for key in ('files', 'records'):
        if not isinstance(saved.get(key), dict) or any(not isinstance(v,str) or len(v) != 64 for v in saved[key].values()):
            raise ValueError('Corrupt continuity snapshot hashes')
    for name in saved['files']:
        safe_relative(root, name)
    current = capture_snapshot(root)
    files = _delta(saved['files'], current['files']); records = _delta(saved['records'], current['records'])
    git = {k: {'before': saved.get('git', {}).get(k), 'after': v} for k, v in current['git'].items() if saved.get('git', {}).get(k) != v}
    changed = set(files['added'] + files['modified'] + files['removed'])
    affected = [{'id': r['id'], 'paths': sorted({e['path'] for e in r.get('evidence', []) if e.get('path') in changed})}
                for r in visible_records(root) if any(e.get('path') in changed for e in r.get('evidence', []))]
    old_hashes, new_hashes = defaultdict(list), defaultdict(list)
    for name in files['removed']: old_hashes[saved['files'][name]].append(name)
    for name in files['added']: new_hashes[current['files'][name]].append(name)
    renames = [{'from': old_hashes[h][0], 'to': new_hashes[h][0], 'reason': 'unique identical content hash'}
               for h in sorted(old_hashes.keys() & new_hashes.keys()) if len(old_hashes[h]) == len(new_hashes[h]) == 1]
    complete = not (saved.get('truncated') or current['truncated'] or saved.get('errors') or current['errors'])
    differences = [name for name, values in (('files',files),('records',records)) if any(values.values())]
    if git: differences.append('git')
    if not complete: differences.append('coverage-incomplete')
    return {'ok': not differences, 'complete': complete, 'legacy': False, 'differences': differences,
            'files': files, 'records': records, 'git': git, 'rename_candidates': renames,
            'affected_records': affected, 'saved_at': saved.get('captured_at'),
            'errors': current['errors'], 'truncated': current['truncated']}


def task_differences(root: Path, task_id: str | None = None) -> dict:
    from .tasks import load_tasks
    data = load_tasks(root)
    tasks = ([data['active']] if data['active'] else []) + list(reversed(data['history']))
    task = next((t for t in tasks if t['status'] != 'done' and (not task_id or t['id'] == task_id)), None)
    if not task: raise ValueError('No unfinished task matches the requested ID')
    return {'task_id': task['id'], 'acceptance': task['acceptance'], 'blockers': task['blockers'],
            'next_actions': task['next_actions'], 'changes': compare_snapshot(root, task.get('checkpoint_snapshot'))}
