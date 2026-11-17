import hashlib, json, os, stat, subprocess, sys, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
from pctx.backup import create_backup, preview_restore, restore_backup, recover_restore, migrate_history, state_digest
from pctx.history import HISTORY_FIELD
from pctx.model import make_record
from pctx.storage import init_context, load_records, upsert_record, write_json_atomic

class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'project';self.root.mkdir();init_context(self.root)
        self.record('Original')
        upsert_record(self.root,make_record(record_type='note',record_id='note.private',statement='Personal private note',sensitivity='private'))
    def record(self,text):return upsert_record(self.root,make_record(record_type='decision',record_id='decision.api',statement=text))
    def archive(self):
        dest=self.base/'backup.zip';create_backup(self.root,dest);return dest
    def test_round_trip_private_guard_preview_and_integrity(self):
        archive=self.archive();self.assertEqual(stat.S_IMODE(archive.stat().st_mode),0o600)
        self.record('Changed');preview=preview_restore(self.root,archive)
        self.assertNotIn('note.private',json.dumps(preview))
        self.record('Changed again')
        with self.assertRaisesRegex(ValueError,'changed'):restore_backup(self.root,archive,preview['expected_state'])
        preview=preview_restore(self.root,archive)
        result=restore_backup(self.root,archive,preview['expected_state'])
        self.assertEqual(load_records(self.root)[0]['statement'],'Original')
        self.assertTrue(Path(result['pre_restore_backup']).is_file());Path(result['pre_restore_backup']).unlink()
        self.assertTrue((self.root/'.project-context/.private/records/note.private.json').exists())
    def test_corruption_traversal_future_schema_rejected_without_mutation(self):
        archive=self.archive();before=state_digest(self.root)
        with zipfile.ZipFile(archive,'a') as z:z.writestr('unexpected','oops')
        with self.assertRaisesRegex(ValueError,'mismatch'):preview_restore(self.root,archive)
        archive.unlink();self.archive()
        with zipfile.ZipFile(archive) as z:data={n:z.read(n) for n in z.namelist()}
        manifest=json.loads(data['BACKUP.json']);data['../escape']=b'escape';manifest['files']['../escape']=hashlib.sha256(b'escape').hexdigest()
        data['BACKUP.json']=json.dumps(manifest).encode()
        with zipfile.ZipFile(archive,'w') as z:
            for n,v in data.items():z.writestr(n,v)
        with self.assertRaisesRegex(ValueError,'Unsafe'):preview_restore(self.root,archive)
        self.assertEqual(before,state_digest(self.root))
        manifest=json.loads((self.root/'.project-context/manifest.json').read_text());manifest['schema_version']=999
        write_json_atomic(self.root/'.project-context/manifest.json',manifest)
        with self.assertRaisesRegex(ValueError,'schema'):migrate_history(self.root)
    def test_legacy_migration_is_explicit_and_preserves_data(self):
        path=self.root/'.project-context/records/decision.api.json';raw=json.loads(path.read_text());raw.pop(HISTORY_FIELD);path.write_text(json.dumps(raw))
        preview=migrate_history(self.root);self.assertEqual(preview['legacy_records'],1)
        self.assertNotIn(HISTORY_FIELD,json.loads(path.read_text()))
        result=migrate_history(self.root,expected_state=preview['expected_state'])
        Path(result['pre_restore_backup']).unlink()
        self.assertEqual(json.loads(path.read_text())[HISTORY_FIELD]['revisions'][0]['record']['statement'],'Original')
        self.assertEqual(migrate_history(self.root)['legacy_records'],0)
    def test_failed_replace_rolls_back_all_memory(self):
        archive=self.archive();self.record('Keep current');before=state_digest(self.root)
        import pctx.backup as backup
        original=backup._replace;count=0
        def fail_once(source,target):
            nonlocal count
            count+=1
            if count==3:raise OSError('interrupted')
            return original(source,target)
        with patch('pctx.backup._replace',side_effect=fail_once):
            with self.assertRaises(OSError):restore_backup(self.root,archive,before)
        self.assertEqual(state_digest(self.root),before)
        self.assertFalse((self.root/'.project-context/.restore-transaction').exists())
    def test_process_crash_requires_recovery_and_restores_previous_state(self):
        archive=self.archive();self.record('Keep current');before=state_digest(self.root)
        code='''import os,sys
from pathlib import Path
import pctx.backup as b
original=b._replace
count=0
def crash(source,target):
 global count
 count+=1
 original(source,target)
 if count==2:os._exit(73)
b._replace=crash
b.restore_backup(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3])
'''
        result=subprocess.run([sys.executable,'-c',code,str(self.root),str(archive),before],capture_output=True)
        self.assertEqual(result.returncode,73,result.stderr)
        with self.assertRaisesRegex(ValueError,'Interrupted restore'):self.record('Must refuse')
        recovered=recover_restore(self.root);self.assertEqual(recovered['action'],'rollback')
        self.assertEqual(state_digest(self.root),before)
