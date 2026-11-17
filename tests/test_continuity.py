from pathlib import Path
import json, subprocess, tempfile, unittest
from pctx.storage import init_context, upsert_record, sha256_file
from pctx.model import make_record
from pctx.continuity import capture_snapshot, compare_snapshot, task_differences
from pctx.tasks import start_task, checkpoint_task, resume_task, load_tasks
from pctx.service import refresh_project

class ContinuityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); init_context(self.root)
        (self.root/'code.py').write_text('one')
    def test_no_git_changes_rename_and_affected_records(self):
        upsert_record(self.root,make_record(record_type='decision',statement='Code contract',record_id='decision.code',evidence=[{'path':'code.py','content_hash':sha256_file(self.root/'code.py')}]))
        saved=capture_snapshot(self.root)
        self.assertTrue(compare_snapshot(self.root,saved)['ok'])
        (self.root/'code.py').rename(self.root/'new.py')
        report=compare_snapshot(self.root,saved)
        self.assertEqual(report['rename_candidates'][0]['to'],'new.py')
        self.assertEqual(report['affected_records'][0]['id'],'decision.code')
    def test_same_git_porcelain_different_content(self):
        def git(*args): return subprocess.run(['git',*args],cwd=self.root,check=True,capture_output=True)
        git('init');git('add','code.py');git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','fixture')
        (self.root/'code.py').write_text('two'); saved=capture_snapshot(self.root)
        status=git('status','--porcelain').stdout
        (self.root/'code.py').write_text('three')
        self.assertEqual(status,git('status','--porcelain').stdout)
        self.assertEqual(compare_snapshot(self.root,saved)['files']['modified'],['code.py'])
    def test_watch_refresh_preserves_checkpoint_pending_and_read_side_effects(self):
        start_task(self.root,'Continue',acceptance=['criterion'],blockers=['network'],next_actions=['verify'])
        checkpoint_task(self.root)
        baseline=load_tasks(self.root)['active']['checkpoint_snapshot']
        (self.root/'code.py').write_text('changed')
        refresh_project(self.root)
        self.assertEqual(load_tasks(self.root)['active']['checkpoint_snapshot'],baseline)
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(task_differences(self.root)['changes']['files']['modified'],['code.py'])
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        resumed=resume_task(self.root)
        self.assertEqual(resumed['blockers'],['network']);self.assertEqual(resumed['next_actions'],['verify'])
        self.assertFalse(resumed['resume_differences']['changes']['ok'])
    def test_coverage_legacy_and_generated_files(self):
        self.assertFalse(compare_snapshot(self.root,None)['ok'])
        saved=capture_snapshot(self.root,max_files=1)
        (self.root/'PROJECT_CONTEXT.md').write_text('generated')
        self.assertTrue(compare_snapshot(self.root,saved)['ok'])
        (self.root/'extra.py').write_text('extra')
        limited=capture_snapshot(self.root,max_files=1)
        self.assertFalse(compare_snapshot(self.root,limited)['complete'])
        limited['schema_version']=999
        with self.assertRaisesRegex(ValueError,'schema'):compare_snapshot(self.root,limited)
    def test_finish_saves_content_after_stale_detection(self):
        from pctx.mcp import handle_request
        from pctx.storage import load_handoff
        def call(name,args):
            response=handle_request(self.root,{'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}},allow_write=True)
            self.assertFalse(response['result']['isError'],response)
        call('pctx_context',{'task':'Fix code'})
        call('pctx_record_update',{'type':'fact','statement':'The code contains one','evidence':['code.py']})
        (self.root/'code.py').write_text('two')
        call('pctx_finish',{'objective':'Fix code','next_actions':['test']})
        self.assertTrue(compare_snapshot(self.root,load_handoff(self.root)['workspace_snapshot'])['ok'])
