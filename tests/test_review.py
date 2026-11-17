import json
from pathlib import Path
import tempfile
import unittest
from pctx.model import make_record
from pctx.storage import init_context, upsert_record, sha256_file
from pctx.review import review_queue, review_record
from pctx.history import record_history
from pctx.mcp import handle_request

class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); init_context(self.root)
        self.file = self.root / 'api.py'; self.file.write_text('version one')
    def record(self, rid='decision.api', statement='API uses version one', **kw):
        return upsert_record(self.root, make_record(record_type='decision', record_id=rid,
            statement=statement, evidence=[{'kind':'file','path':'api.py','content_hash':sha256_file(self.file)}], **kw))
    def test_changed_evidence_guard_correction_and_confirmation(self):
        self.record(state='verified'); self.file.write_text('version two')
        queue = review_queue(self.root); row = queue['records'][0]
        self.assertIn('evidence:changed',row['reasons'])
        with self.assertRaisesRegex(ValueError, 'Human confirmation'):
            review_record(self.root,'decision.api','confirm',expected_revision=1)
        corrected = review_record(self.root,'decision.api','correct',statement='API uses version two',expected_revision=1)
        self.assertEqual(corrected['state'],'inferred')
        with self.assertRaisesRegex(ValueError,'changed'):
            review_record(self.root,'decision.api','confirm',expected_revision=1,actor='user')
        saved = review_record(self.root,'decision.api','confirm',expected_revision=2,actor='user')
        self.assertEqual(saved['evidence'][0]['content_hash'],sha256_file(self.file))
        self.assertEqual(review_queue(self.root)['total'],0)
        self.assertEqual(record_history(self.root,'decision.api',1)['record']['statement'],'API uses version one')
    def test_missing_and_unsafe_evidence_cannot_confirm(self):
        self.record(); self.file.unlink()
        self.assertEqual(review_queue(self.root)['records'][0]['evidence'][0]['status'],'missing')
        with self.assertRaisesRegex(ValueError,'unavailable'):
            review_record(self.root,'decision.api','confirm',expected_revision=1,actor='user')
    def test_candidates_private_and_supersede(self):
        self.record(claim_key='api.version'); self.record('decision.copy', 'API uses version one')
        self.record('decision.v2','API uses version two',claim_key='api.version'); self.record('decision.copy.v2','API uses version two')
        self.record('decision.private',sensitivity='private')
        queue=review_queue(self.root,limit=1)
        self.assertTrue(queue['truncated'])
        self.assertNotIn('decision.private',json.dumps(queue))
        full=review_queue(self.root)
        self.assertNotIn('decision.api',json.dumps(full))  # New claim-key state logically archives its predecessor.
        self.assertNotIn('conflict-candidate',{c['kind'] for c in full['candidates']})
        self.assertIn('duplicate-candidate',{c['kind'] for c in full['candidates']})
        review_record(self.root,'decision.api','supersede',expected_revision=1,replacement_id='decision.v2')
        self.assertEqual(record_history(self.root,'decision.api',2)['record']['superseded_by'],'decision.v2')
        self.assertEqual(record_history(self.root,'decision.v2')['current_revision'],1)
        self.assertNotIn('decision.api',json.dumps(review_queue(self.root)))
    def test_mcp_reads_do_not_write_and_cannot_confirm(self):
        self.record(); before={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        request={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'pctx_review_queue','arguments':{}}}
        response=handle_request(self.root,request)
        self.assertFalse(response['result']['isError'])
        self.assertEqual(before,{p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        request['params']={'name':'pctx_record_review','arguments':{'id':'decision.api','action':'confirm','expected_revision':1}}
        response=handle_request(self.root,request,allow_write=True)
        self.assertTrue(response.get('error') or response['result']['isError'])
    def test_read_tools_on_write_connection_preserve_adapter_drift(self):
        from pctx.service import refresh_project
        refresh_project(self.root,initialize=True)
        target=self.root/'AGENTS.md';target.write_text(target.read_text()+'\nmanual drift\n')
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        request={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'pctx_review_queue','arguments':{}}}
        self.assertFalse(handle_request(self.root,request,allow_write=True)['result']['isError'])
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
