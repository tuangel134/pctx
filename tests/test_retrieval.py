"""Regressions for bounded context, public expansion and explained retrieval."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from pctx.architecture import update_architecture
from pctx.compile import compile_context, search_records
from pctx.mcp import handle_request
from pctx.model import make_record
from pctx.retrieval import read_records
from pctx.storage import init_context, upsert_record
from pctx.tasks import start_task


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        init_context(self.root, 'retrieval')

    def record(self, rid, statement, **kwargs):
        return upsert_record(self.root, make_record(record_id=rid,
            record_type=rid.split('.')[0], statement=statement, **kwargs))

    def call(self, name, args, write=False):
        return handle_request(self.root, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
            'params': {'name': name, 'arguments': args}}, allow_write=write)['result']

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_long_essential_is_identified_without_truncating_statement(self):
        self.record('constraint.signed', 'Preserve releases. ' * 500)
        text, report = compile_context(self.root, task='fix session', budget=256)
        self.assertLessEqual(report['approximate_tokens'], 256)
        self.assertFalse(report['essential_complete'])
        self.assertEqual(report['essential_omitted'], ['constraint.signed'])
        self.assertIn('INCOMPLETE', text)
        self.assertNotIn('Preserve releases.', text)
        self.assertEqual(report['selection'][0]['omission_reason'], 'budget')

    def test_all_task_fields_are_present_or_explicitly_omitted(self):
        actions = [f'Perform required verification {i}' for i in range(35)]
        blockers = ['Schema pending']
        start_task(self.root, 'Resume changes', next_actions=actions, blockers=blockers)
        text, report = compile_context(self.root, task='resume', budget=256)
        for i, value in enumerate(actions):
            self.assertTrue(value in text or f'next_actions:{i}' in report['task_omitted'])
        self.assertTrue(blockers[0] in text or 'blockers:0' in report['task_omitted'])
        self.assertFalse(report['essential_complete'])

    def test_global_constraints_precede_related_decisions(self):
        self.record('constraint.global', 'Preserve release signatures.')
        for i in range(15):
            self.record(f'decision.auth.{i}', 'Authentication sessions use cookies. ' * 12)
        text, report = compile_context(self.root, task='authentication', budget=512)
        self.assertIn('Preserve release signatures.', text)
        self.assertNotIn('constraint.global', report['essential_omitted'])

    def test_evidence_path_beats_unrelated_decision_and_search_explains_it(self):
        self.record('decision.cookie', 'Keep the browser cookie contract.', scope='browser', evidence=[{'path': 'src/auth.py'}])
        self.record('decision.inventory', 'Warehouse inventory allocation policy.', scope='inventory')
        text, report = compile_context(self.root, task='repair src/auth.py', budget=1800)
        self.assertIn('decision.cookie', report['selected'])
        self.assertNotIn('decision.inventory', text)
        results = search_records(self.root, 'src/auth.py')
        self.assertEqual(results[0]['id'], 'decision.cookie')
        self.assertTrue(any(x.startswith('evidence:') for x in results[0]['retrieval']['reasons']))

    def test_explicit_spanish_aliases_and_accent_normalization(self):
        self.record('decision.cookie', 'Authentication sessions use HttpOnly cookies.')
        self.assertEqual(search_records(self.root, 'autenticación y sesión')[0]['id'], 'decision.cookie')

    def test_one_hop_architecture_relation_is_explained(self):
        update_architecture(self.root, nodes=[{'id': 'audio', 'label': 'audio', 'kind': 'module'},
            {'id': 'routing', 'label': 'routing', 'kind': 'module'}],
            edges=[{'source': 'audio', 'target': 'routing', 'label': 'calls'}])
        self.record('decision.devices', 'Preserve the current communication device.', scope='routing')
        results = search_records(self.root, 'repair audio')
        self.assertEqual(results[0]['id'], 'decision.devices')
        self.assertIn('architecture-neighbor: routing', results[0]['retrieval']['reasons'])

    def test_private_and_missing_ids_indistinguishable_and_reports_do_not_leak(self):
        self.record('note.private', 'PRIVATE_MARKER', sensitivity='private')
        self.record('decision.old', 'OLD_MARKER', state='superseded')
        for rid in ('note.private', 'does.not.exist', 'decision.old'):
            with self.assertRaisesRegex(ValueError, '^Record unavailable$'):
                read_records(self.root, record_id=rid)
        text, report = compile_context(self.root, task='PRIVATE_MARKER', budget=512)
        self.assertNotIn('note.private', text + json.dumps(report))
        self.assertNotIn('OLD_MARKER', text + json.dumps(report))
        self.assertFalse(search_records(self.root, 'PRIVATE_MARKER'))

    def test_component_expansion_is_bounded_and_does_not_write(self):
        for i in range(3):
            self.record(f'fact.component.{i}', f'Component fact {i}', evidence=[{'path': f'src/audio/file{i}.py'}])
        before = self.snapshot()
        read = read_records(self.root, component='src/audio', limit=2)
        self.assertEqual((len(read['records']), read['total'], read['truncated']), (2, 3, True))
        self.assertEqual(before, self.snapshot())
        self.assertFalse(read_records(self.root, component='src/audi')['records'])

    def test_cli_report_is_valid_json_and_read_only(self):
        self.record('constraint.essential', 'Keep the release unchanged. ' * 500)
        before = self.snapshot()
        proc = subprocess.run([sys.executable, '-m', 'pctx', '--root', str(self.root),
            'context', '--task', 'repair audio', '--budget', '256', '--json', '--read-only'],
            capture_output=True, text=True, check=True)
        self.assertFalse(json.loads(proc.stdout)['essential_complete'])
        self.assertEqual(before, self.snapshot())

    def test_mcp_budgeted_text_and_on_demand_report_and_expansion(self):
        self.record('constraint.essential', 'Keep the release unchanged. ' * 500)
        before = self.snapshot()
        result = self.call('pctx_context', {'task': 'repair audio', 'budget': 256})
        self.assertLessEqual(len(result['content'][0]['text']), 256 * 4)
        self.assertFalse(result['structuredContent']['essential_complete'])
        report = json.loads(self.call('pctx_context_report', {'task': 'repair audio', 'budget': 256})['content'][0]['text'])
        self.assertEqual(report['essential_omitted'], ['constraint.essential'])
        expanded = json.loads(self.call('pctx_read', {'id': 'constraint.essential'})['content'][0]['text'])
        self.assertEqual(expanded['records'][0]['id'], 'constraint.essential')
        self.assertEqual(before, self.snapshot())

    def test_long_requested_objective_and_read_only_output_are_not_silent(self):
        text, report = compile_context(self.root, task='Inspect the authentication contract. ' * 300, budget=256)
        self.assertIn('requested_objective', report['task_omitted'])
        self.assertIn('INCOMPLETE', text)
        output = self.root / 'unexpected.txt'
        proc = subprocess.run([sys.executable, '-m', 'pctx', '--root', str(self.root),
            'context', '--task', 'inspect', '--read-only', '--output', str(output)], capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
