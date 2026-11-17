import concurrent.futures
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

from pctx.history import HISTORY_FIELD, record_history, restore_record
from pctx.model import make_record
from pctx.retrieval import read_records
from pctx.storage import init_context, load_records, upsert_record, write_json_atomic


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        init_context(self.root)

    def write(self, statement, **kwargs):
        return upsert_record(self.root, make_record(record_type='decision',
            record_id='decision.api', statement=statement, **kwargs))

    def test_idempotence_revision_comparison_and_public_expansion(self):
        self.write('Version one')
        self.write('Version one')
        self.assertEqual(record_history(self.root, 'decision.api')['current_revision'], 1)
        self.write('Version two')
        history = record_history(self.root, 'decision.api', 1, 2)
        self.assertEqual(history['changes']['statement'], {'before': 'Version one', 'after': 'Version two'})
        self.assertNotIn(HISTORY_FIELD, read_records(self.root, record_id='decision.api')['records'][0])

    def test_restore_is_new_inferred_revision_and_rejects_stale_guard(self):
        self.write('Version one', state='verified')
        self.write('Version two', state='verified')
        with self.assertRaisesRegex(ValueError, 'changed'):
            restore_record(self.root, 'decision.api', 1, 1)
        result = restore_record(self.root, 'decision.api', 1, 2)
        self.assertEqual(result['statement'], 'Version one')
        self.assertEqual(result['state'], 'inferred')
        self.assertEqual(result['restored_from'], 1)
        self.assertEqual(record_history(self.root, 'decision.api')['current_revision'], 3)

    def test_legacy_baseline_preserved_on_first_change(self):
        record = make_record(record_type='decision', record_id='decision.api', statement='Legacy value')
        write_json_atomic(self.root / '.project-context/records/decision.api.json', record)
        self.assertTrue(record_history(self.root, 'decision.api')['legacy'])
        self.write('New value')
        self.assertEqual(record_history(self.root, 'decision.api', 1)['record']['statement'], 'Legacy value')

    def test_failed_atomic_replace_preserves_record_and_revisions(self):
        self.write('Preserve this value')
        path = self.root / '.project-context/records/decision.api.json'
        before = path.read_bytes()
        with patch('pctx.storage.os.replace', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                self.write('Interrupted value')
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(record_history(self.root, 'decision.api')['current_revision'], 1)

    def test_corrupt_history_is_not_overwritten(self):
        self.write('Version one')
        path = self.root / '.project-context/records/decision.api.json'
        value = json.loads(path.read_text())
        value[HISTORY_FIELD]['revisions'][0]['digest'] = 'corrupt'
        path.write_text(json.dumps(value))
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'digest'):
            self.write('Version two')
        self.assertEqual(path.read_bytes(), before)

    def test_concurrent_updates_preserve_each_revision(self):
        self.write('Initial value')
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: self.write(f'Concurrent value {i}'), range(8)))
        self.assertEqual(record_history(self.root, 'decision.api')['current_revision'], 9)
        snapshots = [record_history(self.root, 'decision.api', i)['record']['statement'] for i in range(1, 10)]
        self.assertEqual(set(snapshots), {'Initial value'} | {f'Concurrent value {i}' for i in range(8)})

    def test_private_ids_and_history_never_published_implicitly(self):
        self.write('Private first value', sensitivity='private')
        self.write('Private second value', sensitivity='private')
        self.assertFalse(load_records(self.root))
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            record_history(self.root, 'decision.api')
        with self.assertRaisesRegex(ValueError, 'privacy migration'):
            self.write('Publish this value')
        self.assertFalse(load_records(self.root))

    def test_public_to_private_transition_is_rejected_without_exposing_history(self):
        self.write('Public first value')
        self.write('Public second value')
        before=(self.root / '.project-context/records/decision.api.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'privacy migration'):
            self.write('Private replacement', sensitivity='private')
        self.assertEqual(before,(self.root / '.project-context/records/decision.api.json').read_bytes())
        self.assertNotIn('Private replacement',before.decode())

    def test_historical_superseded_decisions_remain_inspectable(self):
        self.write('An older contract')
        self.write('A superseded contract', state='superseded')
        self.assertEqual(record_history(self.root, 'decision.api', 1)['record']['statement'], 'An older contract')
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            read_records(self.root, record_id='decision.api')

    def test_process_writers_do_not_lose_revisions(self):
        self.write('Initial value')
        code = ('import sys; from pathlib import Path; from pctx.storage import upsert_record; '
                'from pctx.model import make_record; upsert_record(Path(sys.argv[1]), '
                'make_record(record_type="decision", record_id="decision.api", statement=sys.argv[2]))')
        children = [subprocess.Popen([sys.executable, '-c', code, str(self.root), f'Process value {i}'],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(6)]
        for child in children:
            _, error = child.communicate(timeout=15)
            self.assertEqual(child.returncode, 0, error.decode())
        self.assertEqual(record_history(self.root, 'decision.api')['current_revision'], 7)

    def test_cli_and_mcp_history_reads_and_restore_permissions(self):
        from pctx.mcp import handle_request
        self.write('First contract')
        self.write('Second contract')
        cmd = [sys.executable, '-m', 'pctx', '--root', str(self.root), 'history', '--id', 'decision.api']
        output = subprocess.run(cmd + ['--revision', '1', '--compare', '2'], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(output.stdout)['changes']['statement']['after'], 'Second contract')
        request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
            'name': 'pctx_record_restore', 'arguments': {'id': 'decision.api', 'revision': 1, 'expected_revision': 2}}}
        denied = handle_request(self.root, request)
        self.assertTrue(denied['result']['isError'])
        restored = handle_request(self.root, request, allow_write=True)
        self.assertFalse(restored['result']['isError'])
        self.assertEqual(record_history(self.root, 'decision.api')['current_revision'], 3)


if __name__ == '__main__':
    unittest.main()
