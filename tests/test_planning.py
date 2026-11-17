import concurrent.futures
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from pctx.compile import compile_context
from pctx.history import restore_record, validate_history
from pctx.mcp import handle_request
from pctx.model import make_record, normalize_record
from pctx.planning import update, query
from pctx.review import review_record, review_queue
from pctx.storage import init_context, load_records, upsert_record

class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); init_context(self.root)
        (self.root/'proof.txt').write_text('Observed acceptance result: pass\n')
    def create(self, id='plan.item', **kw):
        return update(self.root, 'create', id=id, title=kw.pop('title', id), criteria=kw.pop('criteria', ['Acceptance behavior passes']), **kw)
    def detail(self, id='plan.item'):
        return query(self.root, 'detail', id=id, budget=20000)['detail']
    def change(self, action, id='plan.item', **kw):
        return update(self.root, action, id=id, expected_revision=kw.pop('expected_revision', self.detail(id)['current_revision']), **kw)
    def review(self, id='plan.item', **kw):
        return self.change('review', id=id, outcome=kw.pop('outcome', 'passed'), summary=kw.pop('summary', 'Acceptance behavior checked'), reviewer='test suite', evidence=kw.pop('evidence',['proof.txt']), covered_criteria=kw.pop('covered_criteria',[c['id'] for c in self.detail(id)['criteria']]), **kw)
    def verify(self, id='plan.item'):
        self.change('status', id=id, status='done'); self.review(id); return self.change('status', id=id, status='verified')
    def files(self):
        return {p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
    def rpc(self, name, args, write=False):
        return handle_request(self.root, {'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}}, allow_write=write)
    def test_completion_does_not_invent_reviews(self):
        self.create(); self.change('status',status='done')
        self.assertEqual(self.detail()['review_count'],0)
        with self.assertRaisesRegex(ValueError, 'review|Verification'):
            self.change('status',status='verified')
        self.assertEqual(self.detail()['status'],'done')
        self.assertIn('[x] plan.item', (self.root/'PROJECT_CONTEXT.md').read_text())
    def test_all_five_levels_and_unknown_are_explicit(self):
        for difficulty in ['unknown','easy','medium','intermediate','hard','very_hard']:
            self.create('plan.'+difficulty, difficulty=difficulty, difficulty_reason='' if difficulty=='unknown' else 'Classified by actual scope',risk='high')
            page=query(self.root,'list',difficulty=difficulty,ready=True)
            self.assertEqual([r['id'] for r in page['items']],['plan.'+difficulty])
            self.assertEqual(page['items'][0]['risk'],'high')
        self.assertIn('independent',self.detail('plan.easy')['review_guidance'])
        with self.assertRaisesRegex(ValueError,'reason'):
            self.create('plan.no_reason',difficulty='easy')
        self.assertEqual(self.detail('plan.unknown')['difficulty_label'],'Sin clasificar')
    def test_assignment_and_progress_prevent_duplicate_selection(self):
        self.create(); self.assertTrue(self.detail()['ready'])
        self.change('edit',owner='AI session A')
        self.assertEqual(query(self.root,'list',difficulty='unknown',ready=True)['total'],0)
        self.change('edit',owner='');self.change('status',status='in_progress')
        self.assertFalse(self.detail()['ready'])
    def test_children_and_dependencies_block_completion(self):
        self.create('plan.goal',kind='goal');self.create(parent='plan.goal');self.create('plan.dependency')
        self.change('edit',dependencies=['plan.dependency'])
        with self.assertRaisesRegex(ValueError,'unfinished'):
            self.change('status',id='plan.goal',status='done')
        self.assertFalse(self.detail()['ready'])
        with self.assertRaisesRegex(ValueError,'unfinished'):
            self.change('status',status='done')
        self.change('status',id='plan.dependency',status='cancelled',reason='No longer applicable')
        self.assertFalse(self.detail()['ready'])
        with self.assertRaisesRegex(ValueError,'unfinished'):
            self.change('status',status='done')
        self.change('status',id='plan.dependency',status='done')
        self.assertTrue(self.detail()['ready'])
        self.change('status',status='done');self.change('status',id='plan.goal',status='done')
        self.assertEqual(self.detail('plan.goal')['progress']['done'],1)
    def test_parent_verification_requires_verified_children(self):
        self.create('plan.goal',kind='goal');self.create(parent='plan.goal')
        self.change('status',status='done'); self.review('plan.goal')
        with self.assertRaisesRegex(ValueError,'not verified'):
            self.change('status',id='plan.goal',status='verified')
        self.verify();self.review('plan.goal');self.change('status',id='plan.goal',status='verified')
        self.change('status',status='pending')
        self.assertEqual(self.detail('plan.goal')['status'],'needs_review')
        self.assertEqual(self.detail('plan.goal')['declared_status'],'verified')
    def test_changed_missing_and_symlink_evidence_invalidate_verification(self):
        self.create();self.verify();self.assertEqual(self.detail()['status'],'verified')
        (self.root/'proof.txt').write_text('changed')
        self.assertEqual(self.detail()['status'],'needs_review')
        self.assertEqual(self.detail()['review_count'],1)
        (self.root/'proof.txt').unlink();self.assertFalse(self.detail()['review_valid'])
        (self.root/'else.txt').write_text('Observed acceptance result: pass\n')
        (self.root/'proof.txt').symlink_to(self.root/'else.txt')
        self.assertFalse(self.detail()['review_valid'])
    def test_reopen_then_complete_requires_a_new_review(self):
        self.create();self.verify();self.change('status',status='pending');self.change('status',status='done')
        with self.assertRaisesRegex(ValueError,'review'):
            self.change('status',status='verified')
        self.review();self.change('status',status='verified')
        self.assertEqual(self.detail()['review_count'],2)
    def test_edit_and_revert_does_not_resurrect_old_verification(self):
        self.create();self.verify();self.change('edit',title='New behavior');self.change('edit',title='plan.item')
        self.assertFalse(self.detail()['review_valid'])
        with self.assertRaisesRegex(ValueError,'review'):
            self.change('status',status='verified')
    def test_failed_and_inconclusive_reviews_preserve_history(self):
        self.create(kind='bug');self.review(outcome='failed',summary='Acceptance failed',event_id='review-1')
        self.assertEqual(self.detail()['status'],'needs_review');self.assertEqual(self.detail()['review_count'],1)
        self.review(outcome='inconclusive',summary='Hardware unavailable',event_id='review-2')
        self.review(outcome='blocked',summary='Device needed',event_id='review-3')
        self.assertEqual(self.detail()['status'],'blocked')
        history=query(self.root,'history',id='plan.item',budget=20000)
        reviews=[x['review'] for x in history['items'] if x['review']]
        self.assertEqual([x['id'] for x in reviews],['review-3','review-2','review-1'])
        before=self.files();query(self.root,'history',id='plan.item');query(self.root,'summary');self.assertEqual(before,self.files())
    def test_review_retry_is_idempotent_even_after_other_reviews(self):
        self.create();self.review(event_id='same');before=self.files()
        result=self.review(event_id='same',expected_revision=1)
        self.assertTrue(result['already_recorded']);self.assertEqual(before,self.files())
        self.review(event_id='later',outcome='failed',summary='Regression found')
        result=self.review(event_id='same',expected_revision=1)
        self.assertTrue(result['already_recorded']);self.assertEqual(self.detail()['review_count'],2)
        with self.assertRaisesRegex(ValueError,'another result'):
            self.review(event_id='same',summary='Different check')
    def test_missing_or_partial_criteria_and_empty_evidence_cannot_verify(self):
        self.create(criteria=['First behavior','Second behavior'])
        for kw in [{'covered_criteria':[]}, {'covered_criteria':[self.detail()['criteria'][0]['id']]}, {'evidence':[]}]:
            self.review(**kw)
            if kw.get('covered_criteria'):
                self.assertEqual(self.detail()['current_passed_criteria'],kw['covered_criteria'])
            with self.assertRaisesRegex(ValueError,'review|Verification'):
                self.change('status',status='verified')
        with self.assertRaisesRegex(ValueError,'unavailable acceptance'):
            self.review(covered_criteria=['criterion.fake'])
        self.create('plan.empty',criteria=[]);self.review('plan.empty')
        with self.assertRaisesRegex(ValueError,'review|Verification'):
            self.change('status',id='plan.empty',status='verified')
    def test_cycles_missing_parents_and_depth_rejected_atomically(self):
        self.create('plan.parent');self.create(parent='plan.parent')
        before=self.files()
        with self.assertRaisesRegex(ValueError,'cycle'):
            self.change('edit',id='plan.parent',parent='plan.item')
        self.assertEqual(before,self.files())
    def test_combined_hierarchy_dependency_cycle_rejected(self):
        self.create('plan.parent');self.create(parent='plan.parent')
        before=self.files()
        with self.assertRaisesRegex(ValueError,'cycle'):
            self.change('edit',dependencies=['plan.parent'])
        self.assertEqual(before,self.files())
        with self.assertRaisesRegex(ValueError,'unavailable'):
            self.create('plan.missing',parent='plan.notfound')
        parent='plan.parent'
        for i in range(8):
            rid=f'plan.depth{i}';self.create(rid,parent=parent);parent=rid
        with self.assertRaisesRegex(ValueError,'eight'):
            self.create('plan.toodeep',parent=parent)
    def test_stale_revision_and_simultaneous_writers_do_not_overwrite(self):
        self.create()
        def write(owner):
            try:
                update(self.root,'edit',id='plan.item',expected_revision=1,owner=owner)
                return 'saved'
            except ValueError:
                return 'conflict'
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(write,['one','two'])),['saved','conflict'])
        self.assertEqual(self.detail()['current_revision'],2)
    def test_privacy_unsafe_paths_and_generic_write_guards(self):
        self.create();before=self.files()
        for path in ['../proof.txt','/tmp/proof.txt','.env','.project-context/records/x.json','credentials.json']:
            with self.assertRaises(ValueError):self.review(evidence=[path])
        self.assertEqual(before,self.files())
        with self.assertRaises(ValueError):
            make_record(record_type='note',record_id='plan.item',statement='Generic overwrite')
        with self.assertRaisesRegex(ValueError,'managed'):
            restore_record(self.root,'plan.item',1,1)
        with self.assertRaisesRegex(ValueError,'managed'):
            review_record(self.root,'plan.item','correct',expected_revision=1,statement='overwrite')
        self.assertNotIn('plan.item',json.dumps(review_queue(self.root)))
        response=self.rpc('pctx_record_update',{'id':'plan.item','type':'note','statement':'overwrite'},True)
        self.assertTrue(response['result']['isError'])
    def test_probable_secret_rejected_without_partial_write(self):
        self.create();before=self.files()
        with self.assertRaises(ValueError):
            self.change('edit',description='-----BEGIN PRIVATE KEY-----\nprivate material\n-----END PRIVATE KEY-----')
        self.assertEqual(before,self.files())
    def test_mcp_read_only_and_budget_including_wire_metadata(self):
        for i in range(14):self.create(f'plan.item{i}',title='Extensive '+str(i)+' title '*20)
        before=self.files()
        response=self.rpc('pctx_plan',{'action':'list','budget':256},True)
        result=json.loads(response['result']['content'][0]['text'])
        self.assertTrue(result['truncated']);self.assertLessEqual(len(response['result']['content'][0]['text']),1024)
        self.assertEqual(result['next_offset'],len(result['items']));self.assertEqual(before,self.files())
        response=self.rpc('pctx_plan_update',{'action':'create','title':'Forbidden'})
        self.assertTrue(response['result']['isError']);self.assertEqual(before,self.files())
        tools=handle_request(self.root,{'jsonrpc':'2.0','id':1,'method':'tools/list'},allow_write=True)['result']['tools']
        self.assertTrue(next(x for x in tools if x['name']=='pctx_plan')['annotations']['readOnlyHint'])
        self.assertFalse(next(x for x in tools if x['name']=='pctx_plan_update')['annotations']['readOnlyHint'])
    def test_bounded_detail_history_and_pagination(self):
        self.create(description='long '*700)
        result=query(self.root,'detail',id='plan.item',budget=256)
        self.assertNotIn('detail',result);self.assertTrue(result['truncated'])
        for i in range(3):self.review(event_id=f'event{i}',summary='review '*250)
        page=query(self.root,'history',id='plan.item',budget=512)
        self.assertTrue(page['truncated']);self.assertLessEqual(len(json.dumps(page,ensure_ascii=False,separators=(',',':'))),2048)
    def test_context_prioritizes_constraints_and_bounds_checklist(self):
        upsert_record(self.root,make_record(record_type='constraint',record_id='constraint.safe',statement='Preserve existing data'))
        self.create('plan.goal',kind='goal');self.create(parent='plan.goal',difficulty='easy',difficulty_reason='Isolated behavior')
        for budget in [256,512,1000,2000,8000]:
            text, report=compile_context(self.root,task='Test plan',budget=budget)
            self.assertLessEqual(report['approximate_tokens'],budget)
            if report['plan_summary_included']:
                self.assertIn('plan.item',text);self.assertLess(text.index('constraint.safe'),text.index('Goals and checklist'))
            else:
                self.assertTrue(report['plan_summary_omitted']);self.assertIn('Checklist overview omitted',text)
        self.assertIn('plan.item',(self.root/'TASKS.md').read_text())
        text,info=compile_context(self.root);self.assertEqual(text.count('### plan.item'),0)
    def test_cli_and_mcp_use_the_same_portable_records(self):
        command=[sys.executable,'-m','pctx','--root',str(self.root)]
        result=subprocess.run(command+['plan','create','--id','plan.cli','--title','CLI entry','--difficulty','easy','--difficulty-reason','One file','--risk','high'],text=True,capture_output=True,check=True)
        self.assertEqual(json.loads(result.stdout)['current_revision'],1)
        response=self.rpc('pctx_plan',{'action':'list','difficulty':'easy','ready':True})
        self.assertEqual(json.loads(response['result']['content'][0]['text'])['items'][0]['id'],'plan.cli')
        self.assertEqual(normalize_record(load_records(self.root)[0])['checklist']['difficulty'],'easy')
    def test_filter_entire_goal_and_descendants(self):
        self.create('plan.goal',kind='goal');self.create(parent='plan.goal');self.create('plan.other')
        self.assertEqual(query(self.root,'list',goal='plan.goal')['total'],2)
        self.assertEqual(query(self.root,'list',parent='plan.goal')['items'][0]['id'],'plan.item')
        self.assertEqual(query(self.root,'list',parent='root')['total'],2)
    def test_cancel_requires_reason_and_reopen_preserves_reviews(self):
        self.create();self.review(outcome='failed')
        with self.assertRaisesRegex(ValueError,'reason'):
            self.change('status',status='cancelled')
        self.change('status',status='cancelled',reason='User removed this requirement')
        self.assertEqual(self.detail()['review_count'],1)
        self.change('status',status='pending');self.assertEqual(self.detail()['review_count'],1)

    def test_progressive_lookup_searches_description_and_acceptance_without_history(self):
        from pctx.knowledge import lookup, expand
        self.create(description='Negotiate lunar rendezvous protocol', criteria=['Telemetry polarization confirmed'])
        found=lookup(self.root,'lunar rendezvous',kind='record',budget=2000)
        self.assertEqual(found['results'][0]['source'],'record:plan.item')
        found=lookup(self.root,'telemetry polarization',kind='record',budget=2000)
        ref=found['results'][0]['ref']
        self.assertIn('Telemetry polarization',json.dumps(expand(self.root,ref,budget=2000)))
        self.change('edit',description='Current mission protocol',criteria=['New acceptance'])
        with self.assertRaises(ValueError):expand(self.root,ref)
        self.assertEqual(lookup(self.root,'telemetry polarization',kind='record',budget=2000)['results'],[])

    def test_extensive_dependency_chain_does_not_use_python_recursion(self):
        import copy
        self.create('plan.template')
        template=load_records(self.root)[0]
        # Direct fixture writes avoid regenerating all derived files after each insertion.
        for i in range(1100):
            record=copy.deepcopy(template);record.pop('_pctx_history',None)
            record['id']=f'plan.chain{i:04}';record['checklist']['title']=f'Step {i}'
            record['checklist']['dependencies']=[f'plan.chain{i+1:04}'] if i<1099 else []
            upsert_record(self.root,record)
        page=query(self.root,'list',ready=True,budget=512)
        self.assertEqual({x['id'] for x in page['items']},{'plan.chain1099','plan.template'})
        self.assertLessEqual(len(json.dumps(page,ensure_ascii=False,separators=(',',':'))),2048)

    def test_processes_cannot_both_assign_the_same_revision(self):
        self.create()
        command=[sys.executable,'-m','pctx','--root',str(self.root),'plan','edit','--id','plan.item','--expected-revision','1','--owner']
        a=subprocess.Popen(command+['session-A'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        b=subprocess.Popen(command+['session-B'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        a.communicate(timeout=20);b.communicate(timeout=20)
        self.assertCountEqual([a.returncode,b.returncode],[0,1])
        self.assertEqual(self.detail()['current_revision'],2)
    def test_doctor_detects_invalid_verification_and_review_counter_corruption(self):
        from pctx.doctor import run_doctor
        from pctx.history import advance_history
        from pctx.storage import write_json_atomic, records_dir
        from pctx.model import safe_record_filename
        self.create();self.verify();(self.root/'proof.txt').write_text('regression')
        self.assertIn('checklist-review',{x['code'] for x in run_doctor(self.root)['findings']})
        record=load_records(self.root)[0]
        record['checklist']['review_count']=9
        # Even correctly rehashed snapshots cannot silently invent review events.
        record['_pctx_history']=advance_history(None,record)
        write_json_atomic(records_dir(self.root)/safe_record_filename(record['id']),record)
        with self.assertRaisesRegex(ValueError,'count'):
            query(self.root,'summary')
        self.assertIn('checklist-integrity',{x['code'] for x in run_doctor(self.root)['findings']})
    def test_portable_backup_restores_review_history_and_difficulty(self):
        from pctx.backup import create_backup, restore_backup, preview_restore
        self.create(difficulty='intermediate',difficulty_reason='Coordinates two components');self.verify()
        target=Path(self.tmp.name).parent/(Path(self.tmp.name).name+'.zip');self.addCleanup(lambda:target.unlink(missing_ok=True))
        create_backup(self.root,target)
        self.change('edit',title='New definition')
        preview=preview_restore(self.root,target)
        result=restore_backup(self.root,target,preview['expected_state'])
        self.addCleanup(lambda:Path(result['pre_restore_backup']).unlink(missing_ok=True))
        self.assertEqual(self.detail()['difficulty'],'intermediate')
        self.assertEqual(self.detail()['status'],'verified');self.assertEqual(self.detail()['review_count'],1)
    def test_long_history_and_record_metadata_remain_bounded(self):
        self.create(description='A detailed acceptance description '*80,criteria=[f'Criterion {i}: '+'X'*300 for i in range(40)])
        for i in range(20):
            self.review(event_id=f'check-{i}',summary='Observed output '+str(i))
        offset, events=0, []
        while True:
            page=query(self.root,'history',id='plan.item',offset=offset,limit=3,budget=3000)
            self.assertLessEqual(len(json.dumps(page,ensure_ascii=False,separators=(',',':'))),12000)
            events.extend(x['review']['id'] for x in page['items'] if x['review'])
            if page['next_offset'] is None:break
            self.assertGreater(page['next_offset'],offset);offset=page['next_offset']
        self.assertEqual(len(events),20);self.assertEqual(len(set(events)),20)
        self.assertEqual(self.detail()['review_count'],20)


    def test_explicit_fresh_review_clears_stale_record_marker(self):
        from pctx.scan import _mark_stale_records
        self.create();self.verify()
        (self.root/'proof.txt').write_text('A new acceptance run passed')
        _mark_stale_records(self.root,load_records(self.root))
        old=next(r for r in load_records(self.root) if r['id']=='plan.item')
        self.assertEqual(old['state'],'stale')
        self.review()
        current=next(r for r in load_records(self.root) if r['id']=='plan.item')
        self.assertEqual(current['state'],'inferred')
        self.assertNotIn('stale_reason',current);self.assertNotIn('stale_at',current)
        self.assertEqual(self.detail()['review_count'],2)
        self.assertTrue(self.detail()['review_valid'])

if __name__=='__main__':unittest.main()
