"""Private local backups and recoverable, guarded replacement of canonical memory."""
from __future__ import annotations
import hashlib, json, os, shutil, stat, tempfile, uuid, zipfile
from pathlib import Path, PurePosixPath
from .history import HISTORY_FIELD, advance_history, validate_history
from .model import normalize_record, safe_record_filename, utc_now
from .storage import context_dir, load_manifest, load_records, project_lock, write_json_atomic

MANAGED = ('manifest.json', 'records', '.private', 'work', 'architecture.json', 'evidence', 'archive')
MAX_BYTES = 256 * 1024 * 1024

def _hash(data):return hashlib.sha256(data).hexdigest()

def _memory(root: Path) -> dict[str, bytes]:
    from .service import validate_workspace
    root = validate_workspace(root)
    result = {}
    for name in MANAGED:
        path = context_dir(root)/name
        paths = sorted(path.rglob('*')) if path.is_dir() else [path]
        for file in paths:
            if file.is_symlink(): raise ValueError('Backups refuse symlinks')
            if file.is_file(): result[file.relative_to(context_dir(root)).as_posix()] = file.read_bytes()
    return result

def state_digest(root: Path) -> str:
    return _hash(json.dumps({k:_hash(v) for k,v in _memory(root).items()},sort_keys=True).encode())

def _validate(data: dict[str, bytes]) -> dict:
    if 'manifest.json' not in data: raise ValueError('Backup has no manifest')
    if len(data) > 20000 or sum(map(len,data.values())) > MAX_BYTES: raise ValueError('Backup exceeds safety limits')
    for name in data:
        path=PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name or not path.parts or path.parts[0] not in MANAGED:
            raise ValueError('Unsafe backup path')
        if str(path) != name: raise ValueError('Noncanonical backup path')
    with tempfile.TemporaryDirectory(prefix='pctx-validate-') as directory:
        root=Path(directory); base=context_dir(root); base.mkdir(mode=0o700)
        for name,value in data.items():
            path=base/name; path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
        manifest=load_manifest(root)
        from .tasks import load_tasks
        from .architecture import load_architecture
        load_tasks(root);load_architecture(root)
        public=load_records(root);ids=set()
        from .coordination import _records as coordination_records
        coordination_records(root)
        private=[]
        for path in sorted((base/'.private/records').glob('*.json')):
            record=normalize_record(json.loads(path.read_text(encoding='utf-8')));validate_history(record)
            if record['sensitivity'] != 'private':raise ValueError('Private directory contains nonprivate record')
            private.append(record)
        for r in public + private:
            if r['id'] in ids:raise ValueError('Duplicate record identity in backup')
            ids.add(r['id'])
            if r in public and r['sensitivity'] in {'private','secret'}:raise ValueError('Private record in public backup directory')
            relative = ('.private/records/' if r in private else 'records/') + safe_record_filename(r['id'])
            if relative not in data:raise ValueError('Record filename does not match identity')
        for name,value in data.items():
            if name.endswith('.json'):
                raw=json.loads(value)
                if isinstance(raw,dict) and 'schema_version' in raw and raw['schema_version'] != 1:
                    raise ValueError('Unknown schema in backup')
        return {'project_id':manifest['project_id'],'schema_version':manifest['schema_version'],
                'public_records':len(public),'private_records':len(private),'files':len(data)}

def create_backup(root: Path, destination: Path | None = None) -> dict:
    with project_lock(root):
        data=_memory(root); summary=_validate(data)
        if destination is None:
            directory=Path.home()/'pctx-backups';directory.mkdir(mode=0o700,exist_ok=True)
            destination=directory/f"pctx-{summary['project_id'][:8]}-{uuid.uuid4().hex}.zip"
        destination=destination.expanduser().absolute()
        if destination.exists():raise ValueError('Backup destination already exists')
        if root.resolve() == destination.resolve() or root.resolve() in destination.resolve().parents:
            raise ValueError('Choose a backup destination outside the scanned project')
        destination.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,'wb') as handle, zipfile.ZipFile(handle,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                manifest={'format':'pctx-backup','schema_version':1,'created_at':utc_now(),
                          'project_id':summary['project_id'],'files':{k:_hash(v) for k,v in data.items()}}
                archive.writestr('BACKUP.json',json.dumps(manifest,sort_keys=True))
                for name,value in data.items():archive.writestr(name,value)
            validated,_=read_backup(destination)
            return dict(summary,path=str(destination),sha256=_hash(destination.read_bytes()),contains_private=True)
        except BaseException:
            destination.unlink(missing_ok=True);raise

def read_backup(path: Path) -> tuple[dict,dict]:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError,zipfile.BadZipFile) as exc:
        raise ValueError("Cannot read backup archive") from exc
    with archive:
        infos=archive.infolist()
        if len(infos)>20001 or sum(i.file_size for i in infos)>MAX_BYTES:raise ValueError('Backup exceeds safety limits')
        if len({i.filename for i in infos}) != len(infos):raise ValueError('Duplicate archive entries')
        if any(stat.S_ISLNK(i.external_attr >> 16) or i.is_dir() for i in infos):raise ValueError('Backup links or directory entries are not allowed')
        try:manifest=json.loads(archive.read('BACKUP.json'))
        except (KeyError,ValueError):raise ValueError('Invalid backup manifest')
        if not isinstance(manifest,dict) or manifest.get('format')!='pctx-backup' or manifest.get('schema_version')!=1 or not isinstance(manifest.get('files'),dict):raise ValueError('Unsupported backup schema')
        if set(manifest['files']) != {i.filename for i in infos} - {'BACKUP.json'}:raise ValueError('Backup file set mismatch')
        data={name:archive.read(name) for name in manifest['files']}
        if any(_hash(v)!=manifest['files'][name] for name,v in data.items()):raise ValueError('Backup integrity mismatch')
        summary=_validate(data)
        if summary['project_id'] != manifest.get('project_id'):raise ValueError('Backup identity mismatch')
        return data,summary

def _preview(root: Path, data: dict, summary: dict) -> dict:
    if summary['project_id']!=load_manifest(root)['project_id']:raise ValueError('Backup belongs to a different project')
    old=_memory(root)
    # Private names and values are excluded from the preview.
    public=lambda names:sorted(n for n in names if not n.startswith('.private/'))
    return dict(summary,expected_state=state_digest(root),
        added=public(data.keys()-old.keys()),removed=public(old.keys()-data.keys()),
        modified=public(k for k in data.keys() & old.keys() if data[k]!=old[k]),
        private_changes=sum(old.get(k)!=data.get(k) for k in old.keys() | data.keys() if k.startswith('.private/')))

def _restore_data(data):
    # Restoring an old snapshot must never resurrect a worker's expired/released authority.
    result = dict(data)
    invalidated = 0
    from .history import payload
    for name, value in data.items():
        if not name.startswith('records/') or not name.endswith('.json'):
            continue
        record = normalize_record(json.loads(value))
        if 'coordination' in record and record['coordination']['state'] == 'held':
            current = payload(record)
            current['coordination']['state'] = 'released'
            current['coordination']['summary'] = 'Backup restored: reservation released. Inspect working files and claim again before editing.'
            current['updated_at'] = utc_now()
            current[HISTORY_FIELD] = advance_history(record, current)
            result[name] = (json.dumps(current, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
            invalidated += 1
    return result, invalidated

def preview_restore(root: Path, archive: Path) -> dict:
    data,summary=read_backup(archive)
    data, invalidated = _restore_data(data)
    return dict(_preview(root,data,summary), reservations_released=invalidated)

def _replace(source: Path, target: Path):
    if target.is_dir():shutil.rmtree(target)
    elif target.exists():target.unlink()
    if source.exists():os.replace(source,target)

def _rollback(root: Path, journal: dict):
    transaction=context_dir(root)/'.restore-transaction'
    rollback_data = {p.relative_to(transaction/'before').as_posix(): p.read_bytes()
                     for p in (transaction/'before').rglob('*') if p.is_file()}
    _validate(rollback_data)
    for name in MANAGED:
        target=context_dir(root)/name
        # Copy the rollback image first so recovery remains repeatable after a crash.
        source=transaction/'before'/name; temp=transaction/'rollback'/name
        if temp.exists():
            if temp.is_dir():shutil.rmtree(temp)
            else:temp.unlink()
        if source.is_dir():shutil.copytree(source,temp)
        elif source.exists():temp.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,temp)
        _replace(temp,target)
    shutil.rmtree(transaction)

def _apply(root: Path, data: dict, expected_state: str) -> dict:
    if state_digest(root)!=expected_state:raise ValueError('Memory changed; preview again before applying')
    backup=create_backup(root)
    transaction=context_dir(root)/'.restore-transaction';transaction.mkdir(mode=0o700)
    try:
        for name in MANAGED:
            path=context_dir(root)/name; dest=transaction/'before'/name
            if path.is_dir():shutil.copytree(path,dest)
            elif path.exists():dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest)
        for name,value in data.items():
            path=transaction/'after'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
            if name.startswith('.private/'):path.chmod(0o600)
        for directory in (transaction/'after/.private').rglob('*'):
            if directory.is_dir(): directory.chmod(0o700)
        if (transaction/'after/.private').exists(): (transaction/'after/.private').chmod(0o700)
        journal={'schema_version':1,'phase':'prepared','backup':backup['path']}
        write_json_atomic(transaction/'journal.json',journal)
        for name in MANAGED:_replace(transaction/'after'/name,context_dir(root)/name)
        journal['phase']='committed';write_json_atomic(transaction/'journal.json',journal)
    except BaseException:
        if (transaction/'journal.json').exists():_rollback(root,{})
        elif transaction.exists():shutil.rmtree(transaction)
        raise
    shutil.rmtree(transaction)
    cache=context_dir(root)/'.cache'
    if cache.is_dir():shutil.rmtree(cache)
    return {'ok':True,'pre_restore_backup':backup['path'],'state':state_digest(root)}

def restore_backup(root: Path, archive: Path, expected_state: str) -> dict:
    with project_lock(root):
        data,summary=read_backup(archive)
        data, invalidated = _restore_data(data)
        _preview(root,data,summary)
        return dict(_apply(root,data,expected_state), reservations_released=invalidated)

def recover_restore(root: Path) -> dict:
    from .service import validate_workspace
    root=validate_workspace(root)
    with project_lock(root,allow_recovery=True):
        transaction=context_dir(root)/'.restore-transaction'
        if not transaction.exists():return {'ok':True,'recovered':False}
        path=transaction/'journal.json'
        if not path.exists():
            shutil.rmtree(transaction);return {'ok':True,'recovered':True,'action':'discarded incomplete staging'}
        journal=json.loads(path.read_text())
        if journal.get('schema_version')!=1 or journal.get('phase') not in {'prepared','committed'}:raise ValueError('Invalid restore journal; preserve it for inspection')
        if journal['phase']=='prepared':_rollback(root,journal)
        else:shutil.rmtree(transaction)
        return {'ok':True,'recovered':True,'action':'rollback' if journal['phase']=='prepared' else 'completed commit cleanup'}

def migrate_history(root: Path, *, expected_state: str | None = None) -> dict:
    with project_lock(root):
        data=_memory(root);summary=_validate(data);changed=0
        for name,value in list(data.items()):
            if name.startswith(('records/','.private/records/')) and name.endswith('.json'):
                record=normalize_record(json.loads(value))
                if HISTORY_FIELD not in record:
                    record[HISTORY_FIELD]=advance_history(None,record)
                    data[name]=(json.dumps(record,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode();changed+=1
        preview=_preview(root,data,summary);preview['legacy_records']=changed
        preview['migration']='schema 1 stays schema 1; explicitly initialize optional record histories'
        if expected_state is None:return preview
        if not changed:
            if expected_state!=state_digest(root):raise ValueError('Memory changed; preview again')
            return dict(preview,ok=True,changed=False)
        return dict(preview,**_apply(root,data,expected_state),changed=True)
