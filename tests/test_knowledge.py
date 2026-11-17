"""Privacy, freshness, bounded output and portable retrieval contracts."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pctx.compile import compile_context
from pctx.embeddings import LocalEncoder, similarity
from pctx.knowledge import build_index, expand, inventory, lookup, neighbors, wire
from pctx.mcp import handle_request
from pctx.model import make_record
from pctx.storage import init_context, upsert_record, sha256_file


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        init_context(self.root, 'knowledge')

    def doc(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def record(self, rid, statement, **kwargs):
        return upsert_record(self.root, make_record(record_id=rid, record_type=rid.split('.')[0], statement=statement, **kwargs))

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def call(self, name, args):
        return handle_request(self.root, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
            'params': {'name': name, 'arguments': args}}, allow_write=True)['result']

    def test_missing_cache_read_is_ephemeral_and_never_writes(self):
        self.doc('docs/access.md', 'Authentication requires cookie renewal.')
        before = self.snapshot()
        result = lookup(self.root, 'autenticación')
        self.assertEqual(result['index_state'], 'ephemeral:missing')
        self.assertEqual(result['results'][0]['source'], 'file:docs/access.md')
        self.assertEqual(self.snapshot(), before)

    def test_fresh_index_stale_rebuild_and_deleted_source_rejected_without_writes(self):
        path = self.doc('docs/release.md', 'Release uses signed artifacts.')
        build_index(self.root)
        result = lookup(self.root, 'signed')
        ref = result['results'][0]['ref']
        self.assertEqual(result['index_state'], 'persistent:fresh')
        self.assertTrue(build_index(self.root)['reused'])
        path.write_text('Release uses reproducible artifacts.')
        before = self.snapshot()
        self.assertFalse(lookup(self.root, 'signed')['results'])
        self.assertEqual(lookup(self.root, 'reproducible')['index_state'], 'ephemeral:stale')
        with self.assertRaisesRegex(ValueError, 'Fragment unavailable'):
            expand(self.root, ref)
        self.assertEqual(before, self.snapshot())
        path.unlink()
        self.assertFalse(lookup(self.root, 'reproducible')['results'])
        build_index(self.root)
        self.assertEqual(lookup(self.root, 'reproducible')['index_state'], 'persistent:fresh')

    def test_corrupt_cache_is_explicit_ephemeral_and_not_repaired_by_read(self):
        self.doc('README.md', 'Crash recovery checkpoint.')
        build_index(self.root)
        cache = self.root / '.project-context/.cache/knowledge.sqlite3'
        cache.write_bytes(b'broken sqlite')
        before = self.snapshot()
        result = lookup(self.root, 'recovery')
        self.assertEqual(result['index_state'], 'ephemeral:corrupt')
        self.assertTrue(result['results'])
        self.assertEqual(before, self.snapshot())
        build_index(self.root)
        self.assertEqual(lookup(self.root, 'recovery')['index_state'], 'persistent:fresh')

    def test_cache_text_is_never_used_as_source(self):
        self.doc('README.md', 'Current release contract.')
        build_index(self.root)
        db = sqlite3.connect(self.root / '.project-context/.cache/knowledge.sqlite3')
        db.execute('UPDATE search SET terms=?', ('injected malware obsolete',)); db.commit(); db.close()
        result = lookup(self.root, 'injected')
        self.assertEqual(result['index_state'], 'ephemeral:corrupt')
        self.assertFalse(result['results'])
        self.assertNotIn('malware', wire(result))

    def test_private_superseded_history_secrets_ignored_and_symlinks_never_leak(self):
        self.record('note.hidden', 'HIDDEN_MARKER', sensitivity='private')
        self.record('note.old', 'OLD_MARKER')
        self.record('note.old', 'CURRENT_MARKER')
        self.record('note.retired', 'RETIRED_MARKER', state='superseded')
        self.doc('docs/private/notes.md', 'PRIVATE_DOCUMENT')
        self.doc('docs/chat-transcript.md', 'CHAT_DOCUMENT')
        self.doc('docs/innocent.md', 'User: CONVERSATION_DOCUMENT\nAssistant: full conversation\n')
        self.doc('docs/secret.md', 'SECRET_DOCUMENT')
        self.doc('docs/normal.md', 'Secret assignment api_key=' + 'a'*24)
        self.doc('.pctxignore', 'excluded.md\n')
        self.doc('excluded.md', 'EXCLUDED_MARKER')
        self.doc('docs/safe.md', 'Current safe source.')
        (self.root / 'alias.md').symlink_to(self.root / 'docs/private/notes.md')
        build_index(self.root)
        data = wire(inventory(self.root))
        for marker in ('HIDDEN_MARKER', 'OLD_MARKER', 'RETIRED_MARKER', 'PRIVATE_DOCUMENT', 'CHAT_DOCUMENT', 'CONVERSATION_DOCUMENT', 'SECRET_DOCUMENT', 'EXCLUDED_MARKER', 'api_key'):
            self.assertNotIn(marker, data)
        # Current contents are indexed, historical revisions are absent.
        self.assertIn('CURRENT_MARKER', data)
        cache = (self.root / '.project-context/.cache/knowledge.sqlite3').read_bytes()
        self.assertNotIn(b'OLD_MARKER', cache)

    def test_secret_added_after_index_removes_previously_safe_content(self):
        path = self.doc('README.md', 'Safe original needle.')
        build_index(self.root)
        path.write_text('Safe original needle. token=' + 'z'*25)
        self.assertFalse(lookup(self.root, 'needle')['results'])

    def test_limits_json_escaping_pagination_and_excerpt_expansion(self):
        for i in range(5):
            self.doc(f'docs/{i}.md', ('Authentication \\" contract\n' * 1000)[:2400])
        result = lookup(self.root, 'docs/0.md', limit=6, budget=512)
        self.assertLessEqual(len(wire(result)), 512*4)
        self.assertEqual(result['approximate_tokens'], (len(wire(result))+3)//4)
        self.assertTrue(result['truncated'])
        self.assertTrue(result['results'][0]['excerpt'])
        expanded = expand(self.root, result['results'][0]['ref'])
        self.assertGreater(len(expanded['results'][0]['text']), len(result['results'][0]['text']))
        following = lookup(self.root, 'docs/0.md', offset=result['next_offset'], limit=1)
        self.assertNotEqual(following['results'][0]['ref'], result['results'][0]['ref'])
        for budget in (256, 257, 512, 1000, 2000):
            self.assertLessEqual(len(wire(lookup(self.root, 'authentication', budget=budget))), budget*4)

    def test_sql_expression_is_data_and_invalid_query_or_limits_rejected(self):
        self.doc('README.md', 'Authentication safe source.')
        self.assertIsInstance(lookup(self.root, '" OR authentication NOT * : SELECT')['results'], list)
        for kwargs in ({'budget': 255}, {'limit': 31}, {'offset': -1}, {'mode': 'anything'}, {'kind': 'private'}):
            with self.assertRaises(ValueError):
                lookup(self.root, 'authentication', **kwargs)
        for query in ('', 'x'*2001, 'token=' + 'z'*25):
            with self.assertRaises(ValueError): lookup(self.root, query)

    def test_graph_relations_evidence_depth_and_privacy(self):
        self.doc('src/login.py', 'code')
        self.doc('docs/session.md', 'Cookie lifecycle.')
        self.record('decision.cookie', 'Authentication cookie contract.', evidence=[{'path': 'src/login.py'}],
                    links=[{'relation': 'supports', 'target': 'file:docs/session.md'}, {'relation': 'affects', 'target': 'record:note.hidden'}])
        self.record('note.hidden', 'HIDDEN', sensitivity='private')
        self.record('procedure.recovery', 'Reissue the saved credentials.', links=[{'relation': 'depends_on', 'target': 'record:decision.cookie'}])
        graph = neighbors(self.root, 'file:src/login.py', depth=2)
        self.assertTrue(any(e['relation'] == 'supports' for e in graph['edges']))
        self.assertNotIn('note.hidden', wire(graph))
        result = lookup(self.root, 'authentication', kind='document')
        self.assertEqual(result['results'][0]['source'], 'file:docs/session.md')
        self.assertIn('graph:supports', result['results'][0]['reasons'])
        tiny = neighbors(self.root, 'record:decision.cookie', depth=2, limit=1, budget=256)
        self.assertTrue(tiny['truncated'])
        self.assertLessEqual(len(wire(tiny)), 1024)
        with self.assertRaises(ValueError): neighbors(self.root, 'note.hidden')

    def test_links_are_portable_validated_extensions_and_revisioned(self):
        self.record('decision.api', 'API contract.', links=[{'relation': 'affects', 'target': 'file:src/api.py'}])
        result = self.call('pctx_record_update', {'id': 'decision.api', 'type': 'decision', 'statement': 'New API contract.'})
        self.assertFalse(result['isError'])
        self.assertEqual(json.loads(result['content'][0]['text'])['links'][0]['target'], 'file:src/api.py')
        for links in ([{'relation': 'fake', 'target': 'record:x'}], [{'relation': 'affects', 'target': 'file:../outside'}], ['x']):
            before = self.snapshot()
            result = self.call('pctx_record_update', {'id': 'decision.bad', 'type': 'decision', 'statement': 'invalid', 'links': links})
            self.assertTrue(result['isError'])
            self.assertEqual(before, self.snapshot())

    def test_evidence_changes_are_visible_before_refresh(self):
        path = self.doc('src/api.py', 'old')
        self.record('decision.api', 'API contract.', state='verified', evidence=[{'path': 'src/api.py', 'content_hash': sha256_file(path)}])
        build_index(self.root)
        path.write_text('new')
        self.assertEqual(lookup(self.root, 'API contract')['results'][0]['state'], 'stale-evidence')

    def test_document_findings_do_not_displace_essential_context(self):
        self.record('constraint.release', 'Preserve signatures.')
        self.doc('docs/auth.md', 'Authentication renews the cookie before expiry.')
        text, report = compile_context(self.root, task='authentication', budget=2000)
        self.assertTrue(report['essential_complete'])
        self.assertIn('Preserve signatures.', text)
        self.assertIn('renews the cookie', text)
        self.assertTrue(report['documents'])
        self.record('constraint.large', 'Preserve safety ' * 1000)
        text, report = compile_context(self.root, task='authentication', budget=256)
        self.assertFalse(report['essential_complete'])
        self.assertFalse(report['documents'])

    def test_mcp_read_tools_on_write_connection_do_not_mutate(self):
        self.doc('README.md', 'Authentication cookie.')
        self.record('decision.auth', 'Authentication cookie.', evidence=[{'path': 'README.md'}])
        build_index(self.root)
        before = self.snapshot()
        result = self.call('pctx_lookup', {'query': 'authentication', 'budget': 512})
        self.assertFalse(result['isError'])
        self.assertNotIn('structuredContent', result)
        ref = json.loads(result['content'][0]['text'])['results'][0]['ref']
        for tool in ('pctx_expand', 'pctx_neighbors'):
            self.assertFalse(self.call(tool, {'reference': ref})['isError'])
        self.assertEqual(before, self.snapshot())
        listing = handle_request(self.root, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}, allow_write=True)
        self.assertTrue(all(t['annotations']['readOnlyHint'] for t in listing['result']['tools'] if t['name'] in {'pctx_lookup','pctx_expand','pctx_neighbors'}))

    def test_concurrent_atomic_build_and_reads(self):
        self.doc('README.md', 'Concurrent authentication contract.')
        def operation(i):
            return build_index(self.root) if i%2 == 0 else lookup(self.root, 'authentication')
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(operation, range(12)))
        self.assertTrue(all(r.get('results') or r.get('index') == 'ready' for r in results))

    def test_hybrid_has_no_implicit_model_or_download_and_bad_vectors_fail(self):
        self.doc('README.md', 'Cookie renewal.')
        build_index(self.root)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'explicit local model'):
            lookup(self.root, 'session renewal', mode='hybrid')
        with self.assertRaisesRegex(ValueError, 'bundle unavailable'):
            LocalEncoder(self.root / 'missing-model')
        self.assertEqual(before, self.snapshot())
        self.assertAlmostEqual(similarity([1,0], [1,0]), 1)
        for vector in ([1], [float('nan'), 1], [0,0]):
            with self.assertRaises(ValueError): similarity([1,0], vector)

    def test_hybrid_fusion_and_model_identity_using_explicit_test_encoder(self):
        class Encoder:
            fingerprint = 'test-contract-1'
            def __init__(self, path): pass
            def encode(self, texts):
                return [[1.,0.] if 'cookie' in s.lower() or 'entrar' in s else [0.,1.] for s in texts]
        self.doc('docs/session.md', 'Cookie renewal policy.')
        self.doc('docs/warehouse.md', 'Warehouse inventory policy.')
        with patch('pctx.embeddings.LocalEncoder', Encoder):
            build_index(self.root, model='explicit-test-model')
            result = lookup(self.root, '¿Cómo vuelvo a entrar?', mode='hybrid', model='explicit-test-model')
            self.assertEqual(result['results'][0]['source'], 'file:docs/session.md')
            self.assertEqual(result['results'][0]['reasons'], ['local-vector'])
            self.assertTrue(build_index(self.root)['vectors'])
            Encoder.fingerprint = 'different-contract'
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                lookup(self.root, 'sesión', mode='hybrid', model='explicit-test-model')

    def test_coverage_is_explicit_for_large_documents(self):
        self.doc('large.md', 'a'*(256*1024+1))
        self.assertEqual(lookup(self.root, 'anything')['coverage']['limited_sources'], 1)

    def test_index_mcp_requires_write_permission_and_failed_model_preserves_cache(self):
        self.doc('README.md', 'Authentication contract.')
        request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'pctx_index', 'arguments': {}}}
        before = self.snapshot()
        rejected = handle_request(self.root, request, allow_write=False)
        self.assertTrue(rejected['result']['isError'])
        self.assertEqual(before, self.snapshot())
        self.assertFalse(handle_request(self.root, request, allow_write=True)['result']['isError'])
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'bundle unavailable'):
            build_index(self.root, model=str(self.root / 'missing-model'))
        self.assertEqual(before, self.snapshot())

    def test_incomplete_vector_cache_rejects_hybrid_without_mutation(self):
        class Encoder:
            fingerprint = 'explicit-test'
            def __init__(self, path): pass
            def encode(self, texts): return [[1., 0.] for _ in texts]
        self.doc('README.md', 'Authentication cookie.')
        with patch('pctx.embeddings.LocalEncoder', Encoder):
            build_index(self.root, model='explicit-test')
            db = sqlite3.connect(self.root / '.project-context/.cache/knowledge.sqlite3')
            db.execute('DELETE FROM vectors'); db.commit(); db.close()
            before = self.snapshot()
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                lookup(self.root, 'authentication', mode='hybrid', model='explicit-test')
            self.assertEqual(before, self.snapshot())
            self.assertTrue(lookup(self.root, 'authentication')['results'])

    def test_redirected_cache_is_rejected_without_outside_writes(self):
        with tempfile.TemporaryDirectory() as elsewhere:
            (self.root / '.project-context/.cache').rmdir()
            (self.root / '.project-context/.cache').symlink_to(elsewhere, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'redirected'):
                lookup(self.root, 'anything')
            self.assertEqual(list(Path(elsewhere).iterdir()), [])


if __name__ == '__main__': unittest.main()
