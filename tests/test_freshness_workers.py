import concurrent.futures
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from pctx.model import make_record
from pctx.storage import init_context,load_records,upsert_record,load_manifest,save_manifest
from pctx.history import payload,record_history,validate_history
from pctx.retrieval import search,visible_records
from pctx.compile import compile_context,export_context
from pctx.freshness import project,git_evidence,evidence_status
from pctx.briefing import brief
from pctx.verification import verify
from pctx.worker_reports import import_reports,write_report
from pctx.planning import update as plan,query as plan_query
from pctx.coordination import update as reserve,query as leases,active
from pctx.mcp import handle_request
from pctx.service import refresh_project
from pctx.tasks import start_task,load_tasks


class WorkerMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);init_context(self.root)
    def record(self,id='note.current',statement='Pathfinding status resolved',**kw):
        return upsert_record(self.root,make_record(record_id=id,record_type=kw.pop('record_type','note'),statement=statement,state=kw.pop('state','verified'),**kw))
    def raw(self,id):return next(r for r in load_records(self.root) if r['id']==id)
    def rpc(self,name,args,write=False):
        return handle_request(self.root,{'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}},allow_write=write)
    def cli(self,*args,check=True):
        return subprocess.run([sys.executable,'-m','pctx','--root',str(self.root),*args],capture_output=True,text=True,check=check,timeout=15)
    def files(self):return {p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
    def old(self):return (datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=13)).isoformat()
    def check(self,body='print("152/152")\n',**kw):
        (self.root/'check.py').write_text(body)
        return self.record(id='fact.battery',statement='Batería observada',record_type='fact',check={'argv':[sys.executable,'check.py'],'timeout':kw.pop('timeout',3)},**kw)
    def test_explicit_replacement_archives_without_rewriting_old_json(self):
        self.record('note.old','Pathfinding does not compile; T009 review')
        path=self.root/'.project-context/records/note.old.json';old=path.read_bytes()
        self.record('note.new','Pathfinding compiled; T009 resolved',links=[{'relation':'replaces','target':'record:note.old'}])
        self.assertEqual(path.read_bytes(),old)
        self.assertEqual([r['id'] for r in search(self.root,'pathfinding')],['note.new'])
        archived=project(self.root,load_records(self.root),include_archived=True)
        self.assertEqual(next(r for r in archived if r['id']=='note.old')['superseded_by'],'note.new')
        text,_=compile_context(self.root,task='pathfinding',budget=1200)
        self.assertNotIn('does not compile',text);self.assertIn('compiled',text)
        self.assertEqual(record_history(self.root,'note.old')['current_revision'],1)
    def test_claim_key_automatically_replaces_and_chain_does_not_resurrect(self):
        for n in range(3):self.record('note.'+str(n),claim_key='pathfinding.status',scope='runtime')
        self.assertEqual([r['id'] for r in visible_records(self.root)],['note.2'])
        value=payload(self.raw('note.2'));value['links']=[];upsert_record(self.root,value)
        self.assertEqual([r['id'] for r in visible_records(self.root)],['note.2'])
    def test_atomic_claim_key_race_leaves_only_one_current_state(self):
        self.record('note.baseline',claim_key='status')
        def worker(n):return self.record('note.worker'+str(n),claim_key='status')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(worker,[1,2]))
        self.assertEqual(len(visible_records(self.root)),1)
    def test_replacement_cycle_or_missing_private_target_is_rejected(self):
        self.record('note.a');self.record('note.b',links=[{'relation':'replaces','target':'record:note.a'}])
        before=self.files()
        for id in ['note.b','note.missing']:
            with self.assertRaises(ValueError):self.record('note.a',links=[{'relation':'replaces','target':'record:'+id}])
        self.record('note.private',sensitivity='private')
        with self.assertRaises(ValueError):self.record('note.other',links=[{'relation':'replaces','target':'record:note.private'}])
        self.assertNotIn('note.other',[r['id'] for r in load_records(self.root)])
    def test_volatile_13_day_old_verified_claim_is_stale_without_scan(self):
        self.record('note.old','Pathfinding no compila T009 revisión',stability='volatile',created_at=self.old(),updated_at=self.old())
        self.record('note.new','Pathfinding compila T009 resuelta')
        before=self.files();result=search(self.root,'pathfinding T009')
        self.assertEqual(result[0]['id'],'note.new');self.assertEqual(result[1]['state'],'stale')
        self.assertEqual(result[1]['declared_state'],'verified');self.assertIn('expired',result[1]['stale_reason'])
        self.assertEqual(before,self.files())
    def test_expiry_boundaries_and_stable_constraints(self):
        now=datetime.datetime.now(datetime.timezone.utc).timestamp()
        self.record('note.ttl',ttl_seconds=60,updated_at=datetime.datetime.fromtimestamp(now-60,datetime.timezone.utc).isoformat())
        self.record('constraint.old','Keep user data',record_type='constraint',updated_at=self.old())
        rows=project(self.root,load_records(self.root),now=now)
        self.assertEqual(next(r for r in rows if r['id']=='note.ttl')['state'],'stale')
        self.assertEqual(next(r for r in rows if r['id']=='constraint.old')['state'],'verified')
        for kw in [{'ttl_seconds':True},{'ttl_seconds':0},{'expires_at':'tomorrow'},{'expires_at':'2026-10-24T12:00:00'}]:
            with self.assertRaises(ValueError):self.record(**kw)
    def test_recent_state_wins_when_text_matches_equal(self):
        self.record('note.aold','Pathfinding compiled',updated_at=self.old())
        self.record('note.znew','Pathfinding compiled')
        self.assertEqual(search(self.root,'pathfinding')[0]['id'],'note.znew')
        from pctx.knowledge import lookup
        self.assertEqual(lookup(self.root,'pathfinding',kind='record',budget=1000)['results'][0]['source'],'record:note.znew')
    def test_cli_replaces_ttl_quiet_and_mcp_compact(self):
        self.cli('record','--id','note.old','--statement','Old status','--quiet')
        done=self.cli('record','--id','note.new','--statement','New status','--replaces','note.old','--ttl','60','--role','W4','--quiet','--json')
        self.assertEqual(done.stdout,'');self.assertEqual(self.raw('note.new')['roles'],['W4'])
        r=self.rpc('pctx_record_update',{'id':'note.rpc','type':'fact','statement':'Compact status','quiet':True,'ttl_seconds':120,'roles':['W4']},True)
        self.assertFalse(r['result']['isError']);body=json.loads(r['result']['content'][0]['text'])
        self.assertEqual(set(body),{'id','state','current_revision'})
    def test_git_evidence_tracks_branch_advances_and_ref_movement(self):
        def git(*args):return subprocess.run(['git','-C',str(self.root),*args],capture_output=True,text=True,check=True).stdout.strip()
        git('init','-b','main');git('config','user.email','fixture@example.invalid');git('config','user.name','Fixture')
        (self.root/'source.txt').write_text('v1');git('add','source.txt');git('commit','-m','one')
        commit=git('rev-parse','HEAD');proof=git_evidence(self.root,'main@'+commit)
        self.record('fact.branch','Pathfinding compiled on main',record_type='fact',evidence=[proof])
        self.assertEqual(search(self.root,'pathfinding')[0]['state'],'verified')
        (self.root/'source.txt').write_text('v2');git('commit','-am','two')
        result=search(self.root,'pathfinding')[0]
        self.assertEqual(result['state'],'stale');self.assertIn('ref-advanced',result['stale_reason'])
        self.assertEqual(evidence_status(self.root,[proof])[0]['status'],'ref-advanced')
        with self.assertRaises(ValueError):git_evidence(self.root,'main@'+commit)
        with self.assertRaises(ValueError):git_evidence(self.root,'--help')
    def test_check_preview_and_context_never_execute_commands(self):
        self.check('from pathlib import Path\nPath("ran").write_text("yes")\n')
        before=self.files();info=verify(self.root,'fact.battery')
        self.assertFalse(info['executed']);self.assertEqual(info['current_revision'],1)
        compile_context(self.root,task='bateria',budget=1000);brief(self.root)
        self.assertFalse((self.root/'ran').exists());self.assertEqual(before,self.files())
        r=self.rpc('pctx_verify',{'id':'fact.battery','execute':True},True)
        self.assertFalse(r['result']['isError']);self.assertFalse((self.root/'ran').exists())
    def test_explicit_check_observes_pass_and_source_changes_invalidate_it(self):
        self.check()
        with self.assertRaisesRegex(ValueError,'expected_revision'):verify(self.root,'fact.battery',execute=True)
        result=verify(self.root,'fact.battery',execute=True,expected_revision=1)
        self.assertEqual(result['state'],'verified');self.assertEqual(result['result']['exit_code'],0)
        self.assertEqual(search(self.root,'bateria')[0]['state'],'verified')
        self.assertNotIn('152/152',json.dumps(self.raw('fact.battery')))
        (self.root/'check.py').write_text('raise SystemExit(1)\n')
        self.assertEqual(search(self.root,'bateria')[0]['state'],'stale')
    def test_failed_timeout_and_missing_check_are_observed_not_verified(self):
        cases=[('raise SystemExit(2)\n',3),('import time\ntime.sleep(10)\n',1)]
        for body,timeout in cases:
            with self.subTest(body=body):
                self.check(body,timeout=timeout)
                result=verify(self.root,'fact.battery',execute=True,expected_revision=len(validate_history(self.raw('fact.battery'))))
                self.assertEqual(result['state'],'stale')
        record=payload(self.raw('fact.battery'));record['check']['argv']=['pctx-fixture-command-does-not-exist'];upsert_record(self.root,record)
        result=verify(self.root,'fact.battery',execute=True,expected_revision=len(validate_history(self.raw('fact.battery'))))
        self.assertEqual(result['state'],'stale');self.assertIn('launch_error',result['result'])
    def test_check_output_is_bounded_and_never_persisted(self):
        self.check('print("x"*200000)\nprint("pass"+"word="+"a"*25)\n')
        result=verify(self.root,'fact.battery',execute=True,expected_revision=1)
        self.assertEqual(result['state'],'verified');self.assertTrue(result['result']['output_truncated'])
        self.assertEqual(result['result']['output_bytes_hashed'],65536)
        self.assertNotIn('a'*25,json.dumps(self.raw('fact.battery')))
    def test_source_changes_during_check_fail_closed(self):
        self.check('from pathlib import Path\nPath("source.txt").write_text("changed")\n')
        result=verify(self.root,'fact.battery',execute=True,expected_revision=1)
        self.assertEqual(result['state'],'stale')
    def test_mcp_check_can_call_pctx_without_lock_deadlock(self):
        import os
        self.check('import subprocess,sys\nsubprocess.run([sys.executable,"-m","pctx","--root",".","brief","--budget","256"],check=True)\n',timeout=5)
        with patch.dict(os.environ,{'PYTHONPATH':str(Path(__file__).resolve().parent.parent)}):
            r=self.rpc('pctx_verify_run',{'id':'fact.battery','execute':True,'expected_revision':1},True)
        self.assertFalse(r['result']['isError'],r)
        self.assertEqual(json.loads(r['result']['content'][0]['text'])['state'],'verified')
    def test_changed_record_during_check_does_not_attach_old_result(self):
        self.check('import time\ntime.sleep(.2)\n')
        def change():
            time.sleep(.05);self.record('fact.battery','New acceptance claim',check={'argv':[sys.executable,'check.py'],'timeout':3})
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(change)
            with self.assertRaisesRegex(ValueError,'changed meanwhile'):verify(self.root,'fact.battery',execute=True,expected_revision=1)
            pending.result()
        self.assertNotIn('verification',self.raw('fact.battery'))
    def test_brief_role_is_small_fixed_and_preserves_global_constraints(self):
        plan(self.root,'create',id='plan.worker_W4',title='W4 integrate runtime',owner='runtime-W4',criteria=['Validate runtime integration'])
        self.record('constraint.data','Preserve user data',record_type='constraint')
        self.record('issue.w3','W3 only blocker',record_type='issue',roles=['W3'])
        self.record('issue.w4','W4 runtime blocked',record_type='issue',roles=['W4'])
        start_task(self.root,'Coordinator global trace')
        before=self.files();result=brief(self.root,budget=800,role='W4')
        for text in ['Objetivo:','Siguiente paso:','Restricciones:','Bloqueos:','Últimos cambios:','W4 integrate runtime','Preserve user data','W4 runtime blocked']:
            self.assertIn(text,result['text'])
        self.assertNotIn('W3 only blocker',result['text']);self.assertNotIn('Coordinator global trace',result['text'])
        self.assertLessEqual((len(result['text'])+3)//4,800);self.assertEqual(before,self.files())
    def test_brief_tiny_budget_discloses_missing_essentials(self):
        for n in range(8):self.record('constraint.'+str(n),'Preserve data '+'x'*700,record_type='constraint')
        result=brief(self.root,budget=128)
        self.assertLessEqual(result['approximate_tokens'],128);self.assertFalse(result['essential_complete']);self.assertGreater(result['omitted'],0)
        self.assertIn('INCOMPLETOS',result['text'])
    def test_brief_cli_and_mcp_are_read_only(self):
        self.record(roles=['W4'])
        before=self.files()
        result=self.cli('brief','--role','W4','--budget','800')
        self.assertIn('PCTX brief',result.stdout);self.assertLessEqual((len(result.stdout)+3)//4,800)
        r=self.rpc('pctx_brief',{'role':'W4','budget':800},True)
        self.assertFalse(r['result']['isError']);self.assertFalse(r['result']['structuredContent']['essential_complete']);self.assertEqual(before,self.files())
    def test_report_import_is_idempotent_and_stays_inferred(self):
        folder=self.root/'.delegacion';folder.mkdir()
        path=folder/'HECHO-W4.md';path.write_text('# Runtime\nBatería 152/152 según W4.\n\n## Bloqueo\nFalta probar Android.\n')
        result=import_reports(self.root,paths=['.delegacion/HECHO-W4.md'])
        self.assertEqual(result['created'],2)
        records=load_records(self.root);self.assertTrue(all(r['state']=='inferred' and r['roles']==['W4'] for r in records))
        self.assertEqual({r['type'] for r in records},{'attempt','issue'})
        before=self.files();again=import_reports(self.root,paths=['.delegacion/HECHO-W4.md'])
        self.assertEqual(again['unchanged'],2);self.assertEqual(before,self.files())
    def test_appended_integration_sections_do_not_invalidate_previous_entries(self):
        path=self.root/'INTEGRACION-LOG.md';path.write_text('## W4 primera\nRuntime unido.\n')
        first=import_reports(self.root,paths=[path.name]);id=first['ids'][0];old=self.raw(id)
        path.write_text(path.read_text()+'\n## W3 segunda\nFiguras unidas.\n')
        second=import_reports(self.root,paths=[path.name])
        self.assertEqual(second['created'],1);self.assertEqual(second['unchanged'],1)
        self.assertEqual(len(validate_history(self.raw(id))),len(validate_history(old)))
        self.assertEqual(evidence_status(self.root,self.raw(id)['evidence'])[0]['status'],'current')
    def test_edited_report_updates_same_id_and_removed_section_is_stale(self):
        path=self.root/'HECHO-W4.md';path.write_text('# Runtime\nPrimera revisión.\n')
        id=import_reports(self.root,paths=[path.name])['ids'][0]
        path.write_text('# Runtime\nSegunda revisión.\n')
        self.assertEqual(search(self.root,'runtime')[0]['state'],'stale')
        update=import_reports(self.root,paths=[path.name]);self.assertEqual(update['updated'],1);self.assertEqual(update['ids'],[id])
        self.assertEqual(self.raw(id)['state'],'inferred')
        path.write_text('# Otro\nLa sección anterior se retiró.\n')
        self.assertEqual(search(self.root,'runtime')[0]['state'],'stale')
    def test_report_batch_rejects_secret_transcript_and_symlink_without_partial_import(self):
        (self.root/'HECHO-W4.md').write_text('A valid report')
        bad=self.root/'HECHO-W3.md';bad.write_text('password='+'a'*25)
        before=self.files()
        with self.assertRaises(ValueError):import_reports(self.root,paths=['HECHO-W4.md','HECHO-W3.md'])
        self.assertEqual(before,self.files())
        bad.write_text('user: hello\nassistant: hello')
        with self.assertRaises(ValueError):import_reports(self.root,paths=['HECHO-W3.md'])
        (self.root/'link.md').symlink_to(self.root/'HECHO-W4.md')
        with self.assertRaises(ValueError):import_reports(self.root,paths=['link.md'])
    def test_imported_code_blocks_never_become_checks_or_execute(self):
        p=self.root/'HECHO-W4.md';p.write_text('# Informe\nRevisar runtime.\n```bash\ntouch OWNED\n```\n')
        import_reports(self.root,paths=[p.name]);record=load_records(self.root)[0]
        self.assertNotIn('check',record);self.assertNotIn('touch OWNED',record['statement']);self.assertFalse((self.root/'OWNED').exists())
    def test_report_write_without_reservation_is_limited_and_guarded(self):
        first=write_report(self.root,path='.delegacion/HECHO-W4.md',text='# Runtime\nPrueba reportada.',role='W4')
        self.assertEqual(active(self.root),[]);self.assertTrue(first['changed'])
        with self.assertRaisesRegex(ValueError,'expected_hash'):
            write_report(self.root,path='.delegacion/HECHO-W4.md',text='Overwrite')
        with self.assertRaises(ValueError):write_report(self.root,path='src/main.py',text='Code')
        again=write_report(self.root,path='.delegacion/HECHO-W4.md',text='Next step',append=True)
        duplicate=write_report(self.root,path='.delegacion/HECHO-W4.md',text='Next step',append=True)
        self.assertFalse(duplicate['changed'])
        write_report(self.root,path='.delegacion/HECHO-W4.md',text='# Updated\nReady',expected_hash=duplicate['content_hash'])
    def test_safe_hidden_reservation_and_old_expiry_cleanup_keep_checkpoints(self):
        plan(self.root,'create',id='plan.worker_T009',title='Worker task')
        with patch('pctx.coordination.time.time',return_value=1000):
            first=reserve(self.root,'claim',session_id='W4',task_id='T009',paths=['.delegacion/worker'],ttl=60,summary='Core drafted; review pending')
        with patch('pctx.coordination.time.time',return_value=1060):
            next=reserve(self.root,'claim',session_id='W3',task_id='plan.worker_T009',paths=['.delegacion/worker'])
            old=leases(self.root,'detail',id=first['id'])['detail']
            self.assertEqual(old['state'],'released');self.assertEqual(old['status'],'expired');self.assertEqual(old['summary'],first['summary'])
            released=reserve(self.root,'release',id=first['id'],session_id='W4',expected_revision=1,summary='Late checkpoint')
            self.assertTrue(released['already_released']);self.assertFalse(released['summary_saved'])
            self.assertEqual(active(self.root)[0]['id'],next['id'])
        for path in ['.git/config','.env','.project-context/records','.ssh/id','../outside']:
            with self.assertRaises(ValueError):reserve(self.root,'claim',session_id='W4',task_id='T009',paths=[path])
    def test_cleanup_is_explicit_write_and_missing_task_errors_name_root(self):
        with self.assertRaisesRegex(ValueError,'same --root'):
            reserve(self.root,'claim',session_id='W4',task_id='T009',paths=['src/runtime'])
        self.assertEqual(reserve(self.root,'cleanup')['expired_released'],0)
        r=self.rpc('pctx_coordination_update',{'action':'cleanup'},False)
        self.assertTrue(r['result']['isError'])
    def test_released_lease_survives_changed_evidence_and_legacy_stale_revision(self):
        from pctx.scan import scan_project
        from pctx.storage import sha256_file
        plan(self.root,'create',id='plan.worker',title='Worker task')
        (self.root/'report.md').write_text('Original handoff')
        lease=reserve(self.root,'claim',session_id='W4',task_id='plan.worker',paths=['src/runtime'])
        released=reserve(self.root,'release',id=lease['id'],session_id='W4',expected_revision=lease['current_revision'],summary='Work handed off')
        record=payload(self.raw(lease['id']))
        record['evidence']=[{'path':'report.md','content_hash':sha256_file(self.root/'report.md')}]
        upsert_record(self.root,record)
        before=record_history(self.root,lease['id'])['current_revision']
        (self.root/'report.md').write_text('New report, same released reservation')
        scan_project(self.root)
        self.assertEqual(record_history(self.root,lease['id'])['current_revision'],before)
        record['state']='stale';record['stale_reason']='Legacy scanner evidence update'
        upsert_record(self.root,record)
        self.assertEqual(active(self.root),[])
        self.assertEqual(leases(self.root,'detail',id=lease['id'])['detail']['state'],'released')
        record['coordination']['state']='held'
        upsert_record(self.root,record)
        with self.assertRaisesRegex(ValueError,'lifecycle'):
            active(self.root)
    def test_manual_export_policy_preserves_generated_files_on_writes(self):
        self.record();export_context(self.root)
        self.cli('adapters','sync','--targets','agents,claude')
        result=self.cli('export','--policy','manual','--json')
        initial={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in [self.root/'PROJECT_CONTEXT.md',self.root/'CLAUDE.md']}
        self.cli('record','--id','note.new','--statement','Fresh worker state','--quiet')
        self.rpc('pctx_record_update',{'id':'note.rpc','type':'fact','statement':'Worker update','quiet':True},True)
        for p,value in initial.items():self.assertEqual((p.read_bytes(),p.stat().st_mtime_ns),value)
        text,_=compile_context(self.root,task='worker',budget=1200);self.assertIn('Fresh worker state',text)
        self.cli('export','--json');self.assertIn('Fresh worker state',(self.root/'PROJECT_CONTEXT.md').read_text())
    def test_deterministic_auto_export_and_adapters_keep_mtime_on_same_data(self):
        self.record();self.cli('export');self.cli('adapters','sync','--targets','agents,claude')
        paths=[self.root/'PROJECT_CONTEXT.md',self.root/'CLAUDE.md']
        self.cli('export');before={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in paths}
        self.cli('export');self.cli('adapters','sync','--targets','agents,claude')
        self.assertEqual(before,{p:(p.read_bytes(),p.stat().st_mtime_ns) for p in paths})
    def test_mcp_tool_modes_and_cli_quiet_calls(self):
        catalog=handle_request(self.root,{'jsonrpc':'2.0','id':1,'method':'tools/list'},allow_write=False)['result']['tools']
        names={t['name'] for t in catalog}
        self.assertTrue({'pctx_brief','pctx_verify'}.issubset(names));self.assertNotIn('pctx_verify_run',names);self.assertNotIn('pctx_import_reports',names)
        result=self.cli('call','pctx_brief','--args','{"budget":800}','--quiet');self.assertEqual(result.stdout,'')
        report=self.rpc('pctx_report',{'path':'.delegacion/HECHO-W4.md','text':'# W4\nInforme seguro','role':'W4'},True)
        self.assertFalse(report['result']['isError'],report)
        imported=self.rpc('pctx_import_reports',{'paths':['.delegacion/HECHO-W4.md']},True)
        self.assertFalse(imported['result']['isError'])
        refused=self.rpc('pctx_verify_run',{'id':'unknown','execute':False,'expected_revision':1},True)
        self.assertTrue(refused['result']['isError'])
    def test_git_checklist_review_becomes_outdated_when_branch_advances(self):
        def git(*a):return subprocess.run(['git','-C',str(self.root),*a],check=True,capture_output=True,text=True).stdout.strip()
        git('init','-b','main');git('config','user.email','fixture@example.invalid');git('config','user.name','Fixture')
        (self.root/'source.py').write_text('v1');git('add','source.py');git('commit','-m','one')
        plan(self.root,'create',id='plan.git',title='Git proof',criteria=['Current branch checked'])
        d=plan_query(self.root,'detail',id='plan.git')['detail']
        plan(self.root,'review',id='plan.git',expected_revision=1,outcome='passed',summary='Branch checked',reviewer='fixture',evidence=['git:main'],covered_criteria=[d['criteria'][0]['id']])
        plan(self.root,'status',id='plan.git',expected_revision=2,status='verified')
        self.assertEqual(plan_query(self.root,'detail',id='plan.git')['detail']['status'],'verified')
        (self.root/'source.py').write_text('v2');git('commit','-am','two')
        self.assertEqual(plan_query(self.root,'detail',id='plan.git')['detail']['status'],'needs_review')
    def test_observed_test_counts_must_agree_with_the_claim(self):
        self.check()
        value=payload(self.raw('fact.battery'));value['statement']='Batería 153/153';upsert_record(self.root,value)
        result=verify(self.root,'fact.battery',execute=True,expected_revision=2)
        self.assertEqual(result['state'],'stale');self.assertEqual(result['result']['observed_counts']['total'],152)
        value=payload(self.raw('fact.battery'));value['statement']='Batería 152/152';upsert_record(self.root,value)
        result=verify(self.root,'fact.battery',execute=True,expected_revision=len(validate_history(self.raw('fact.battery'))))
        self.assertEqual(result['state'],'verified');self.assertIn('run_id',result['result'])
    def test_public_hidden_git_source_changes_invalidate_machine_check(self):
        def git(*a):return subprocess.run(['git','-C',str(self.root),*a],check=True,capture_output=True,text=True).stdout.strip()
        git('init','-b','main');git('config','user.email','fixture@example.invalid');git('config','user.name','Fixture')
        folder=self.root/'.github/workflows';folder.mkdir(parents=True);p=folder/'tests.yml';p.write_text('version one')
        self.check();git('add','.github/workflows/tests.yml','check.py');git('commit','-m','source')
        self.assertEqual(verify(self.root,'fact.battery',execute=True,expected_revision=1)['state'],'verified')
        p.write_text('version two')
        self.assertEqual(search(self.root,'bateria')[0]['state'],'stale')
    def test_concurrent_report_appends_preserve_both_workers(self):
        def append(n):return write_report(self.root,path='.delegacion/INTEGRACION-LOG.md',text=f'## W{n}\nWorker {n} integrated',append=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(append,[3,4]))
        text=(self.root/'.delegacion/INTEGRACION-LOG.md').read_text()
        self.assertIn('Worker 3 integrated',text);self.assertIn('Worker 4 integrated',text)
        self.assertEqual(len(load_records(self.root)),2)
        self.assertEqual({r['roles'][0] for r in load_records(self.root)},{'W3','W4'})
    def test_git_cache_compares_each_record_own_commit(self):
        def git(*a):return subprocess.run(['git','-C',str(self.root),*a],check=True,capture_output=True,text=True).stdout.strip()
        git('init','-b','main');git('config','user.email','fixture@example.invalid');git('config','user.name','Fixture')
        p=self.root/'source.txt';p.write_text('one');git('add','source.txt');git('commit','-m','one')
        old=git_evidence(self.root,'main')
        p.write_text('two');git('commit','-am','two')
        new=git_evidence(self.root,'main')
        self.record('fact.old','Old pathfinding',record_type='fact',evidence=[old])
        self.record('fact.new','New pathfinding',record_type='fact',evidence=[new])
        rows={r['id']:r for r in visible_records(self.root)}
        self.assertEqual(rows['fact.old']['state'],'stale');self.assertEqual(rows['fact.new']['state'],'verified')
    def test_unchanged_scanner_git_fact_is_live_even_after_volatile_ttl(self):
        from pctx.scan import git_snapshot
        snapshot=git_snapshot(self.root)
        self.record('fact.snapshot','Current Git identity',record_type='fact',stability='volatile',updated_at=self.old(),evidence=[{'kind':'git-snapshot',**{k:snapshot[k] for k in ['is_git','head','branch','status_hash']}}])
        self.assertEqual(visible_records(self.root)[0]['state'],'verified')
    def test_repeated_context_calls_do_not_churn_identical_exports(self):
        self.cli('adapters','sync','--targets','agents,claude')
        self.cli('context','--task','Same objective','--budget','1200')
        self.cli('context','--task','Same objective','--budget','1200')
        paths=[self.root/'PROJECT_CONTEXT.md',self.root/'CLAUDE.md']
        before={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in paths}
        self.cli('context','--task','Same objective','--budget','1200')
        self.assertEqual(before,{p:(p.read_bytes(),p.stat().st_mtime_ns) for p in paths})
    def test_explicit_expiry_is_respected_even_with_live_git_snapshot(self):
        from pctx.scan import git_snapshot
        snapshot=git_snapshot(self.root)
        self.record('fact.snapshot','Expiring Git observation',record_type='fact',stability='volatile',ttl_seconds=1,updated_at=self.old(),evidence=[{'kind':'git-snapshot','head':snapshot['head'],'status_hash':snapshot['status_hash']}])
        self.assertEqual(visible_records(self.root)[0]['state'],'stale')
    def test_verification_refuses_superseded_check_and_respects_fixed_expiry(self):
        self.check(expires_at=self.old())
        result=verify(self.root,'fact.battery',execute=True,expected_revision=1)
        self.assertEqual(result['state'],'stale')
        self.record('fact.replacement','New battery status',record_type='fact',links=[{'relation':'replaces','target':'record:fact.battery'}])
        with self.assertRaisesRegex(ValueError,'superseded'):verify(self.root,'fact.battery')
    def test_shared_integration_log_retains_each_sections_worker_role(self):
        write_report(self.root,path='.delegacion/INTEGRACION-LOG.md',text='W3 integration complete',append=True,role='W3')
        write_report(self.root,path='.delegacion/INTEGRACION-LOG.md',text='W4 runtime complete',append=True,role='W4')
        rows=load_records(self.root)
        self.assertEqual(len(rows),2);self.assertEqual({r['roles'][0] for r in rows},{'W3','W4'})
        result=brief(self.root,role='W4')['text']
        self.assertIn('W4 runtime complete',result);self.assertNotIn('W3 integration complete',result);self.assertIn('[inferred]',result)
    def test_reviewed_imported_report_remains_importable_without_losing_confirmation(self):
        from pctx.review import review_record
        path=self.root/'HECHO-W4.md';path.write_text('# Runtime\nIntegrated according to worker.\n')
        id=import_reports(self.root,paths=[path.name])['ids'][0]
        review_record(self.root,id,'confirm',expected_revision=1,actor='user')
        result=import_reports(self.root,paths=[path.name])
        self.assertEqual(result['unchanged'],1);self.assertEqual(self.raw(id)['state'],'user_asserted')
        path.write_text('# Runtime\nA new worker report revision.\n')
        self.assertEqual(import_reports(self.root,paths=[path.name])['updated'],1)
        self.assertEqual(self.raw(id)['state'],'inferred')
    def test_existing_decision_cli_still_supports_explicit_replacement(self):
        self.cli('decision','--id','decision.old','--statement','Old architecture')
        self.cli('decision','--id','decision.new','--statement','New architecture','--replaces','decision.old')
        self.assertEqual([r['id'] for r in search(self.root,'architecture')],['decision.new'])
    def test_report_globs_do_not_silently_omit_files_beyond_batch_limit(self):
        for i in range(201):(self.root/f'HECHO-W{i}.md').write_text('A worker report')
        with self.assertRaisesRegex(ValueError,'200 reports'):
            import_reports(self.root,patterns=['HECHO-*.md'])
        self.assertEqual(load_records(self.root),[])
    def test_archived_record_does_not_create_current_evidence_warnings(self):
        from pctx.doctor import run_doctor
        p=self.root/'proof.txt';p.write_text('old proof')
        self.record('note.old','Old current state',evidence=[{'path':'proof.txt','content_hash':hashlib.sha256(p.read_bytes()).hexdigest()}])
        self.record('note.new','New current state',links=[{'relation':'replaces','target':'record:note.old'}])
        p.write_text('new proof')
        findings=run_doctor(self.root)['findings']
        self.assertFalse(any(f.get('path')=='note.old' and f['code'] in {'stale-evidence','record-validity'} for f in findings))
