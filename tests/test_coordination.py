import concurrent.futures
import json
import multiprocessing
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pctx.coordination import query, update, active
from pctx.planning import update as plan_update, query as plan_query
from pctx.storage import init_context, load_records
from pctx.mcp import handle_request
from pctx.history import restore_record, validate_history
from pctx.model import make_record
from pctx.review import review_record
from pctx.compile import compile_context
from pctx.tasks import load_tasks, start_task


def claim_worker(root, task, gate, output):
    gate.wait(10)
    try:
        update(Path(root), 'claim', session_id=task, task_id=task, paths=['shared/module.py'])
        output.put('won')
    except ValueError as e:
        output.put(str(e))


class CoordinationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); init_context(self.root)
        for id in ['plan.a','plan.b']:
            plan_update(self.root,'create',id=id,title=id,criteria=['Acceptance passes'])
        (self.root/'proof.txt').write_text('pass')
    def claim(self, **kw):
        return update(self.root,'claim',session_id=kw.pop('session_id','AI A'),task_id=kw.pop('task_id','plan.a'),paths=kw.pop('paths',['src/a']),**kw)
    def detail(self,id='plan.a'):
        return plan_query(self.root,'detail',id=id,budget=20000)['detail']
    def change(self,lease,action,**kw):
        return update(self.root,action,id=lease['id'],session_id=kw.pop('session_id',lease['session_id']),expected_revision=kw.pop('expected_revision',lease['current_revision']),**kw)
    def rpc(self,name,args,write=False):
        return handle_request(self.root,{'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}},allow_write=write)
    def files(self):
        return {p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
    def test_claim_hides_work_without_rewriting_checklist(self):
        before=self.detail(); lease=self.claim()
        after=self.detail()
        self.assertTrue(after['working']);self.assertFalse(after['ready'])
        self.assertEqual(after['current_revision'],before['current_revision'])
        self.assertEqual(after['review_count'],0);self.assertEqual(after['status'],'pending')
        self.assertEqual(after['reservations'][0]['id'],lease['id'])
        ready=plan_query(self.root,'list',ready=True)
        self.assertEqual([x['id'] for x in ready['items']],['plan.b'])
    def test_tasks_and_path_prefixes_conflict_but_siblings_do_not(self):
        self.claim()
        for task,paths in [('plan.a',['other']),('plan.b',['src/a/login.py']),('plan.b',['src']),('plan.b',['SRC/A'])]:
            with self.assertRaisesRegex(ValueError,'conflict'):
                self.claim(task_id=task,session_id='AI B',paths=paths)
        other=self.claim(task_id='plan.b',session_id='AI B',paths=['src/ab'])
        self.assertEqual(other['status'],'active')
    def test_parent_child_conflicts_and_scope_edit_guard(self):
        plan_update(self.root,'edit',id='plan.a',expected_revision=1,kind='goal')
        plan_update(self.root,'create',id='plan.child',title='Child',parent='plan.a')
        lease=self.claim(task_id='plan.child')
        with self.assertRaisesRegex(ValueError,'conflict'):
            self.claim(paths=['elsewhere'])
        with self.assertRaisesRegex(ValueError,'reserved'):
            plan_update(self.root,'create',id='plan.other',title='Other',parent='plan.a')
        with self.assertRaisesRegex(ValueError,'reserved'):
            plan_update(self.root,'edit',id='plan.b',expected_revision=1,parent='plan.a')
        self.assertTrue(self.detail('plan.a')['working'])
        self.change(lease,'release',summary='Child checkpoint ready for coordinator')
    def test_renew_release_guards_and_handoff(self):
        with patch('pctx.coordination.time.time',return_value=1000): lease=self.claim(ttl=60)
        with patch('pctx.coordination.time.time',return_value=1010):
            for kw in [{'session_id':'AI B'},{'expected_revision':0},{'expected_revision':True}]:
                with self.assertRaises(ValueError):self.change(lease,'renew',**kw)
            renewed=self.change(lease,'renew',summary='Core done; tests remain')
            self.assertEqual(renewed['expires_at'],1070);self.assertEqual(renewed['ttl'],60)
            with self.assertRaisesRegex(ValueError,'immutable'):
                self.change(renewed,'renew',paths=['new'])
            with self.assertRaisesRegex(ValueError,'summary'):
                self.change(renewed,'release')
            released=self.change(renewed,'release',summary='Core done; next worker should run tests')
            self.assertEqual(released['status'],'released')
            self.assertFalse(self.detail()['working']);self.assertTrue(self.detail()['ready'])
            with self.assertRaisesRegex(ValueError,'released'):
                self.change(released,'renew')
            self.assertEqual(query(self.root,'history',id=lease['id'])['total'],3)
    def test_expiry_is_read_only_and_stale_holder_cannot_renew_or_update(self):
        with patch('pctx.coordination.time.time',return_value=1000):lease=self.claim(ttl=60)
        before=self.files()
        with patch('pctx.coordination.time.time',return_value=1060):
            self.assertEqual(active(self.root),[])
            self.assertEqual(query(self.root)['items'][0]['status'],'expired')
            self.assertTrue(self.detail()['ready'])
            self.assertEqual(before,self.files())
            with self.assertRaisesRegex(ValueError,'expired'):
                self.change(lease,'renew')
            with self.assertRaisesRegex(ValueError,'expired'):
                plan_update(self.root,'status',id='plan.a',expected_revision=1,status='in_progress',lease_id=lease['id'],session_id='AI A')
            new=self.claim(session_id='AI B')
            self.assertNotEqual(new['id'],lease['id'])
            with self.assertRaisesRegex(ValueError,'reserved'):
                plan_update(self.root,'status',id='plan.a',expected_revision=1,status='done',lease_id=lease['id'],session_id='AI A')
            self.change(lease,'release',summary='Interrupted; inspect files before resuming')
            self.assertEqual(active(self.root)[0]['id'],new['id'])
    def test_checklist_owner_can_change_status_with_active_lease(self):
        lease=self.claim()
        with self.assertRaisesRegex(ValueError,'reserved'):
            plan_update(self.root,'status',id='plan.a',expected_revision=1,status='in_progress')
        plan_update(self.root,'status',id='plan.a',expected_revision=1,status='in_progress',session_id='AI A',lease_id=lease['id'])
        self.assertEqual(self.detail()['status'],'in_progress')
    def test_heartbeats_do_not_invalidate_evidence_or_review_counts(self):
        lease=self.claim()
        detail=self.detail()
        kwargs={'session_id':'AI A','lease_id':lease['id']}
        plan_update(self.root,'review',id='plan.a',expected_revision=1,outcome='passed',summary='Acceptance checked',reviewer='tester',evidence=['proof.txt'],covered_criteria=[c['id'] for c in detail['criteria']],**kwargs)
        detail=self.detail();self.assertTrue(detail['review_valid'])
        self.change(lease,'renew',summary='Evidence checked; ready for review')
        after=self.detail();self.assertTrue(after['review_valid']);self.assertEqual(after['review_count'],1)
        self.assertEqual(after['current_revision'],detail['current_revision'])
    def test_clock_anomaly_retains_reservation_until_owner_releases(self):
        with patch('pctx.coordination.time.time',return_value=1000):lease=self.claim()
        with patch('pctx.coordination.time.time',return_value=999):
            self.assertEqual(active(self.root)[0]['status'],'clock_anomaly')
            with self.assertRaisesRegex(ValueError,'conflict'):self.claim(session_id='AI B')
            with self.assertRaisesRegex(ValueError,'clock'):self.change(lease,'renew')
            self.change(lease,'release',summary='Clock changed; coordinator will inspect')
            self.assertEqual(active(self.root),[])
    def test_private_unsafe_alias_paths_and_secrets_rejected_atomically(self):
        (self.root/'real').mkdir();(self.root/'link').symlink_to(self.root/'real',target_is_directory=True)
        (self.root/'hard').hardlink_to(self.root/'proof.txt')
        before=self.files()
        for paths in [['../outside'],['/tmp/a'],['src/../a'],['src//a'],['src/*.py'],['src\\a'],['.project-context'],['.env'],['credentials.json'],['a.pem'],['link/a'],['hard'],['a','a'],[]]:
            with self.assertRaises(ValueError):self.claim(paths=paths)
        for ttl in [0,True,59,3601,1.5]:
            with self.assertRaises(ValueError):self.claim(ttl=ttl)
        with self.assertRaises(ValueError):self.claim(summary='password='+'a'*24)
        self.assertEqual(before,self.files())
    def test_assignment_dependencies_and_closed_tasks_respected(self):
        plan_update(self.root,'edit',id='plan.a',expected_revision=1,owner='AI B')
        with self.assertRaisesRegex(ValueError,'owner'):self.claim()
        plan_update(self.root,'edit',id='plan.a',expected_revision=2,owner='',dependencies=['plan.b'])
        with self.assertRaisesRegex(ValueError,'dependencies'):self.claim()
        plan_update(self.root,'status',id='plan.b',expected_revision=1,status='done')
        with self.assertRaisesRegex(ValueError,'closed'):self.claim(task_id='plan.b')
        self.claim()
    def test_generic_tools_cannot_replace_review_or_restore_reservation(self):
        lease=self.claim()
        with self.assertRaisesRegex(ValueError,'Reserved'):
            make_record(record_type='note',record_id=lease['id'],statement='Replace')
        with self.assertRaisesRegex(ValueError,'managed'):
            restore_record(self.root,lease['id'],1,1)
        with self.assertRaisesRegex(ValueError,'managed'):
            review_record(self.root,lease['id'],'correct',expected_revision=1,statement='Replace',actor='agent')
        response=self.rpc('pctx_record_update',{'id':lease['id'],'statement':'Replace'},True)
        self.assertTrue(response['result']['isError'])
    def test_read_only_mcp_budgets_and_no_global_task_clobber(self):
        start_task(self.root,'Coordinator task');before=load_tasks(self.root)
        lease=self.claim()
        self.assertEqual(before,load_tasks(self.root))
        catalog=handle_request(self.root,{'jsonrpc':'2.0','id':1,'method':'tools/list'},allow_write=False)['result']['tools']
        self.assertIn('pctx_coordination',{x['name'] for x in catalog})
        self.assertNotIn('pctx_coordination_update',{x['name'] for x in catalog})
        files=self.files()
        for budget in [256,512,2000]:
            result=query(self.root,budget=budget)
            self.assertLessEqual((len(json.dumps(result,ensure_ascii=False,separators=(',',':')))+3)//4,budget)
            self.assertLessEqual(result['tokens_estimate'],budget)
        self.assertEqual(files,self.files())
        blocked=self.rpc('pctx_coordination_update',{'action':'release','session_id':'AI A','id':lease['id']})
        self.assertTrue(blocked['result']['isError'])
        text,info=compile_context(self.root,task='implement src/a',budget=2000)
        self.assertIn('reserved by AI A',text);self.assertLessEqual(info['approximate_tokens'],2000)
        self.assertEqual(before,load_tasks(self.root))
    def test_history_pagination_and_lookup_excludes_heartbeat_records(self):
        from pctx.knowledge import inventory
        lease=self.claim(summary='uniquecoordinatesentinel')
        for i in range(6):lease=self.change(lease,'renew',summary='Checkpoint '+str(i))
        page=query(self.root,'history',id=lease['id'],limit=2,budget=1000)
        self.assertEqual(len(page['items']),2);self.assertEqual(page['next_offset'],2)
        nextpage=query(self.root,'history',id=lease['id'],offset=2,limit=2)
        self.assertLess(nextpage['items'][0]['revision'],page['items'][-1]['revision'])
        inv=inventory(self.root)
        self.assertNotIn('uniquecoordinatesentinel',json.dumps(inv))
    def test_two_real_processes_cannot_win_overlapping_claim(self):
        ctx=multiprocessing.get_context('spawn'); gate=ctx.Event();output=ctx.Queue()
        processes=[ctx.Process(target=claim_worker,args=(str(self.root),task,gate,output)) for task in ['plan.a','plan.b']]
        for p in processes:p.start()
        gate.set();results=[output.get(timeout=20) for _ in processes]
        for p in processes:p.join(20);self.assertEqual(p.exitcode,0)
        self.assertEqual(results.count('won'),1)
        self.assertEqual(sum('conflict' in r for r in results),1)
        self.assertEqual(len(active(self.root)),1)
    def test_cli_and_mcp_share_canonical_lease(self):
        result=subprocess.run([sys.executable,'-m','pctx','--root',str(self.root),'coordinate','claim','--session-id','CLI worker','--task-id','plan.a','--path','src/a'],check=True,capture_output=True,text=True)
        lease=json.loads(result.stdout)
        response=self.rpc('pctx_coordination',{'action':'detail','id':lease['id']})
        current=json.loads(response['result']['content'][0]['text'])['detail']
        self.assertEqual(current['session_id'],'CLI worker')
        response=self.rpc('pctx_coordination_update',{'action':'release','id':lease['id'],'session_id':'CLI worker','expected_revision':1,'summary':'MCP picked up CLI checkpoint'},True)
        self.assertFalse(response['result'].get('isError',False))
        self.assertEqual(query(self.root)['items'][0]['status'],'released')

    def test_backup_restore_invalidates_old_reservations_preserving_history(self):
        from pctx.backup import create_backup, preview_restore, restore_backup
        lease=self.claim()
        backupdir=tempfile.TemporaryDirectory();self.addCleanup(backupdir.cleanup)
        backup=create_backup(self.root,Path(backupdir.name)/'saved.zip')
        self.change(lease,'release',summary='Work paused before restore')
        preview=preview_restore(self.root,Path(backup['path']))
        self.assertEqual(preview['reservations_released'],1)
        result=restore_backup(self.root,Path(backup['path']),preview['expected_state'])
        self.assertEqual(result['reservations_released'],1)
        self.assertEqual(active(self.root),[])
        restored=query(self.root,'detail',id=lease['id'])['detail']
        self.assertEqual(restored['status'],'released');self.assertEqual(restored['current_revision'],2)
        self.assertIn('Backup restored',restored['summary'])
        self.claim(session_id='AI B')
    def test_corrupt_lifecycle_history_fails_closed_and_doctor_reports_it(self):
        from pctx.history import content_digest
        from pctx.doctor import run_doctor
        lease=self.claim();self.change(lease,'renew',summary='Current checkpoint')
        path=self.root/'.project-context/records'/ (lease['id']+'.json')
        record=json.loads(path.read_text())
        rev=record['_pctx_history']['revisions'][0]
        rev['record']['coordination']['session_id']='Forged earlier owner'
        rev['digest']=content_digest(rev['record'])
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError,'history'):
            self.claim(task_id='plan.b',paths=['other'])
        report=run_doctor(self.root)
        self.assertTrue(any(f['code']=='coordination-integrity' for f in report['findings']))
    def test_renewal_revision_race_has_one_winner(self):
        lease=self.claim()
        def renew(i):
            try:self.change(lease,'renew',summary='Worker checkpoint '+str(i));return 'won'
            except ValueError as e:return str(e)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(renew,range(2)))
        self.assertEqual(results.count('won'),1)
        self.assertEqual(sum('revision' in r for r in results),1)

    def test_heartbeat_does_not_invalidate_retrieval_index_fingerprint(self):
        from pctx.knowledge import inventory, build_index, lookup
        lease=self.claim()
        before=inventory(self.root)['digest'];build_index(self.root)
        lease=self.change(lease,'renew',summary='Checkpoint is not searchable source knowledge')
        self.assertEqual(before,inventory(self.root)['digest'])
        self.assertEqual(lookup(self.root,'Acceptance',budget=512)['index_state'],'persistent:fresh')

    def test_empty_heartbeat_keeps_last_checkpoint(self):
        lease=self.claim(summary='Implementation ready; next worker reviews error handling')
        renewed=self.change(lease,'renew',summary='')
        self.assertEqual(renewed['summary'],lease['summary'])
