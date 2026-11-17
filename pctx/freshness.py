"""Live validity of canonical knowledge; reading never executes stored commands."""
from __future__ import annotations
from datetime import datetime, timezone
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

VOLATILE_TTL = 86400
BAD_EVIDENCE = {'changed', 'missing', 'unsafe', 'unreadable', 'not-file', 'ref-advanced', 'git-unavailable', 'workspace-changed'}


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Timestamp must be an ISO UTC date')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('Timezone required')
        return parsed.timestamp()
    except (ValueError, OverflowError) as exc:
        raise ValueError('Invalid timestamp; include a timezone') from exc


def validate_metadata(record):
    if 'ttl_seconds' in record:
        value = record['ttl_seconds']
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 31536000:
            raise ValueError('ttl_seconds must be between 1 and 31536000')
    if record.get('expires_at') is not None:
        timestamp(record['expires_at'])
    if 'roles' in record:
        if not isinstance(record['roles'], list) or len(record['roles']) > 30 or any(not isinstance(x, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', x) for x in record['roles']):
            raise ValueError('roles must contain simple worker labels such as W4')
    if 'check' in record:
        check = record['check']
        if not isinstance(check, dict) or set(check) != {'argv', 'timeout'} or not isinstance(check['argv'], list) or not 1 <= len(check['argv']) <= 64 or any(not isinstance(x, str) or not x or len(x) > 1000 or any(c in x for c in '\n\r\0') for x in check['argv']):
            raise ValueError('Check requires a bounded argv array and timeout')
        if isinstance(check['timeout'], bool) or not isinstance(check['timeout'], int) or not 1 <= check['timeout'] <= 3600:
            raise ValueError('Check timeout must be between 1 and 3600 seconds')


def _git(root, args):
    result = subprocess.run(['git', '--no-optional-locks', '-C', str(root), *args], capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise ValueError('Git evidence unavailable in this project')
    return result.stdout.strip()


def git_evidence(root: Path, reference: str):
    if not isinstance(reference, str) or len(reference) > 300 or not reference or any(c in reference for c in '\n\r\0'):
        raise ValueError('Invalid Git reference')
    branch, sep, commit = reference.rpartition('@')
    if not sep:
        branch, commit = reference, ''
    if not branch or branch.startswith('-') or not re.fullmatch(r'[A-Za-z0-9_./-]+', branch) or '..' in branch:
        raise ValueError('Use a branch/ref name or branch@commit')
    resolved = _git(root, ['rev-parse', '--verify', '--end-of-options', branch + '^{commit}'])
    if commit:
        if not re.fullmatch(r'[a-fA-F0-9]{7,64}', commit):
            raise ValueError('Commit must be a hexadecimal hash')
        pinned = _git(root, ['rev-parse', '--verify', '--end-of-options', commit + '^{commit}'])
        if pinned != resolved:
            raise ValueError('Branch no longer points to the requested commit')
    return {'kind': 'git', 'branch': branch, 'commit': resolved, 'ref': branch + '@' + resolved}


def workspace_digest(root):
    from .scan import collect_files, git_snapshot
    from .storage import sha256_file
    files = collect_files(root, max_files=10001)
    if len(files) > 10000:
        raise ValueError('Workspace exceeds verification snapshot coverage')
    values = {p.relative_to(root).as_posix(): sha256_file(p) for p in files}
    try:
        tracked = _git(root, ['ls-files','-z']).split('\0')
    except (OSError,ValueError,subprocess.TimeoutExpired): tracked=[]
    from .public_paths import resolve
    from .scan import _is_context_output
    for name in tracked:
        if not name or name in values or _is_context_output(name): continue
        try:
            path = resolve(root,name)
            if path.is_file(): values[name]=sha256_file(path)
        except (OSError,ValueError): continue
    snapshot = git_snapshot(root)
    return hashlib.sha256(json.dumps({'files': values, 'head': snapshot['head'], 'branch': snapshot['branch']}, sort_keys=True).encode()).hexdigest()


def evidence_status(root, evidence, cache=None):
    from .storage import safe_relative, sha256_file
    cache = {} if cache is None else cache
    result = []
    for item in evidence:
        kind = item.get('kind')
        if kind == 'report':
            from .worker_reports import section_status
            try: status = section_status(root, item, cache)
            except (OSError, ValueError, UnicodeError): status = 'unsafe'
            result.append({'kind':kind,'path':item.get('path'),'section':item.get('section'),'status':status}); continue
        if kind == 'git-snapshot' or (kind == 'git' and 'head' in item and not item.get('branch')):
            if 'git-snapshot' not in cache:
                from .scan import git_snapshot
                cache['git-snapshot'] = git_snapshot(root)
            current = cache['git-snapshot']
            fields = ('is_git','head','branch','remote','status_hash')
            status = 'current' if all(item[key] == current.get(key) for key in fields if key in item) else 'ref-advanced'
            result.append({'kind': 'git-snapshot', 'status': status, 'current_commit':current.get('head')})
            continue
        if kind == 'git':
            key = ('git', item.get('branch'))
            if key not in cache:
                try: cache[key] = git_evidence(root, item.get('branch', ''))['commit']
                except (ValueError, OSError, subprocess.TimeoutExpired): cache[key] = None
            current = cache[key]
            status = 'git-unavailable' if current is None else 'current' if current == item.get('commit') else 'ref-advanced'
            result.append({'kind': 'git', 'branch': item.get('branch'), 'commit': item.get('commit'), 'current_commit': current, 'status': status})
            continue
        if kind == 'workspace':
            if 'workspace' not in cache:
                try: cache['workspace'] = workspace_digest(root)
                except (OSError, ValueError): cache['workspace'] = None
            result.append({'kind': kind, 'status': 'current' if cache['workspace'] == item.get('content_hash') and cache['workspace'] else 'workspace-changed'})
            continue
        relative = item.get('path')
        if not relative or relative == '.':
            continue
        key = ('file', relative)
        if key not in cache:
            try:
                name = Path(relative)
                if '.private' in name.parts or name.name == '.env' or name.name.startswith('.env.') or name.suffix.lower() in {'.key', '.pem', '.p12', '.pfx'}:
                    raise ValueError('Private evidence unavailable')
                path = safe_relative(root, relative)
                if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root.parent):
                    raise ValueError('Symlink evidence unavailable')
                cache[key] = ('missing', None) if not path.exists() else ('not-file', None) if not path.is_file() else ('available', sha256_file(path))
            except ValueError: cache[key] = ('unsafe', None)
            except OSError: cache[key] = ('unreadable', None)
        status, actual = cache[key]
        expected = item.get('content_hash')
        if status == 'available':
            status = 'current' if expected == actual else 'changed' if expected else 'unverified'
        result.append({'path': relative, 'status': status, 'expected_hash': expected, 'current_hash': actual})
    return result


def replacement_map(records):
    result = {}
    for r in records:
        if r.get('superseded_by'):
            result[r['id']] = r['superseded_by']
    for r in sorted(records, key=lambda r: (r.get('updated_at', ''), r['id'])):
        for link in r.get('links', []):
            if link['relation'] == 'replaces' and link['target'].startswith('record:'):
                result[link['target'][7:]] = r['id']
    return result


def project(root, records, *, include_archived=False, now=None):
    from .history import payload
    now = time.time() if now is None else now
    replacements, cache = replacement_map(records), {}
    result = []
    for raw in records:
        record = payload(raw)
        declared = record['state']
        if record['id'] in replacements:
            record.update(state='superseded', superseded_by=replacements[record['id']])
        if record['state'] == 'superseded':
            if include_archived: result.append(record)
            continue
        reasons = []
        expiry = record.get('expires_at')
        ttl = record.get('ttl_seconds', VOLATILE_TTL if record.get('stability') == 'volatile' else None)
        try:
            deadline = timestamp(expiry) if expiry else timestamp(record.get('updated_at')) + ttl if ttl is not None else None
            snapshot_proof = any(e.get('kind')=='git-snapshot' or (e.get('kind')=='git' and 'head' in e and not e.get('branch')) for e in record.get('evidence',[]))
            if deadline is not None and now >= deadline and not (snapshot_proof and 'ttl_seconds' not in record and not expiry):
                reasons.append('expired')
        except (ValueError, TypeError):
            if ttl is not None or expiry: reasons.append('invalid expiry date')
        checked = evidence_status(root, record.get('evidence', []), cache)
        reasons.extend(e.get('kind', e.get('path', 'evidence')) + ': ' + e['status'] for e in checked if e['status'] in BAD_EVIDENCE)
        if record.get('check') and declared == 'verified' and (not record.get('verification') or record['verification'].get('check_sha256') != hashlib.sha256(json.dumps(record['check'],sort_keys=True).encode()).hexdigest()):
            record.update(state='inferred', stale_reason='Check command configured but not executed for this definition')
        if reasons:
            record.update(state='stale', stale_reason='; '.join(reasons))
        if reasons or declared == 'stale' or record['state'] != declared:
            record['declared_state'] = declared
        result.append(record)
    return result


def recency(record, now=None):
    try:
        age = max(0, (time.time() if now is None else now) - timestamp(record['updated_at']))
        return round(40 / (1 + int(age // 3600) / 24), 4)
    except (ValueError, KeyError):
        return 0
