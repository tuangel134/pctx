"""Regressions for the W7 report against PCTX 0.7.0."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from pctx.briefing import brief
from pctx.doctor import run_doctor
from pctx.history import record_history
from pctx.mcp import handle_request
from pctx.model import make_record
from pctx.planning import update as plan
from pctx.storage import init_context, load_records, sha256_file, upsert_record
from pctx.tasks import start_task


class BriefFollowupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        init_context(self.root)

    def cli(self, *args, check=True):
        return subprocess.run([sys.executable, '-m', 'pctx', '--root', str(self.root), *args],
                              capture_output=True, text=True, check=check, timeout=15)

    def record(self, id, text, type='note', **extra):
        return upsert_record(self.root, make_record(record_id=id, record_type=type,
                                                    statement=text, **extra))

    def files(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file()}

    def test_w7_cli_task_update_shows_shared_trace_without_inventing_assignment(self):
        self.cli('task', 'start', '--title', 'Meta Microbastion')
        self.cli('task', 'update', '--next-action', 'Integrar colisiones', '--blocker', 'Falta bateria')
        before = self.files()
        x = json.loads(self.cli('brief', '--budget', '800', '--role', 'W7', '--json').stdout)
        for value in ['[global] Meta Microbastion', '[global] Integrar colisiones',
                      '[global] Falta bateria', 'Checkpoint de tarea actualizado']:
            self.assertIn(value, x['text'])
        self.assertIn('Sin datos específicos para W7', x['text'])
        self.assertFalse(x['role_matched'])
        self.assertFalse(x['essential_complete'])
        self.assertLessEqual(x['approximate_tokens'], 800)
        self.assertEqual(self.files(), before)

    def test_untagged_actions_are_shared_and_explicit_other_roles_are_excluded(self):
        start_task(self.root, 'Meta global')
        self.record('next.global', 'Paso compartido', type='next_action')
        self.record('issue.global', 'Bloqueo compartido', type='issue')
        self.record('next.W3', 'Accion reservada W3', type='next_action')
        self.record('next.W7-but-W3', 'Roles explicitos prevalecen', type='next_action', roles=['W3'])
        self.record('attempt.other', 'Solo W3', type='attempt', roles=['W3'])
        text = brief(self.root, role='W7')['text']
        self.assertIn('[global] Paso compartido', text)
        self.assertIn('Bloqueo compartido', text)
        self.assertIn('Registro actualizado', text)
        for value in ['Accion reservada W3', 'Roles explicitos prevalecen', 'Solo W3']:
            self.assertNotIn(value, text)
        self.record('next.W7', 'Trabajo asignado W7', type='next_action', roles=['W7'])
        x = brief(self.root, role='W7')
        self.assertTrue(x['role_matched'])
        self.assertTrue(x['essential_complete'])
        self.assertLess(x['text'].index('Trabajo asignado W7'), x['text'].index('[global] Paso compartido'))

    def test_worker_objective_precedes_shared_context_and_other_plans_are_filtered(self):
        start_task(self.root, 'Meta coordinador', next_actions=['Paso global'], blockers=['Dependencia global'])
        plan(self.root, 'create', id='plan.worker_W7', title='Integracion W7', owner='worker-W7', criteria=['Validar runtime'])
        plan(self.root, 'create', id='plan.worker_W3', title='No compartir tarea W3', owner='worker-W3')
        text = brief(self.root, role='W7')['text']
        self.assertIn('Integracion W7', text)
        self.assertIn('Validar runtime', text)
        self.assertIn('[global] Paso global', text)
        self.assertIn('[global] Dependencia global', text)
        self.assertNotIn('Meta coordinador', text)
        self.assertNotIn('No compartir tarea W3', text)

    def test_shared_handoff_is_available_but_stale_handoff_is_not_trusted(self):
        p = self.root / 'state.md'
        p.write_text('current')
        self.record('work.handoff', 'Estado guardado', type='handoff', objective='Objetivo guardado',
                    next_actions=['Siguiente del handoff'], blockers=['Bloqueo guardado'], changed_files=['runtime.py'],
                    evidence=[{'path': p.name, 'content_hash': sha256_file(p)}])
        x = brief(self.root, role='W7')
        for value in ['[global] Objetivo guardado', '[global] Siguiente del handoff', '[global] Bloqueo guardado', '[global] runtime.py']:
            self.assertIn(value, x['text'])
        p.write_text('changed')
        text = brief(self.root, role='W7')['text']
        self.assertNotIn('Objetivo guardado', text)
        self.assertNotIn('Siguiente del handoff', text)

    def test_mcp_shared_context_is_bounded_and_read_only(self):
        start_task(self.root, 'Meta global', next_actions=['Paso '+str(n)+'x'*500 for n in range(10)])
        before = self.files()
        x = handle_request(self.root, {'jsonrpc':'2.0', 'id':1, 'method':'tools/call',
                           'params':{'name':'pctx_brief', 'arguments':{'role':'W7', 'budget':256}}}, allow_write=True)['result']
        self.assertFalse(x['isError'])
        self.assertIn('[global]', x['content'][0]['text'])
        self.assertLessEqual(x['structuredContent']['approximate_tokens'], 256)
        self.assertGreater(x['structuredContent']['omitted'], 0)
        self.assertFalse(x['structuredContent']['role_matched'])
        self.assertEqual(self.files(), before)

    def test_record_ttl_units_are_stored_as_seconds_and_bad_units_do_not_write(self):
        for value, seconds in [('86400',86400), ('60s',60), ('30m',1800), ('24h',86400), ('1d',86400), ('1w',604800)]:
            self.cli('record', '--id', 'next.step', '--type', 'next_action', '--statement', 'Validar runtime', '--ttl', value, '--quiet')
            self.assertEqual(next(r for r in load_records(self.root) if r['id']=='next.step')['ttl_seconds'], seconds)
        before = self.files()
        for value in ['0', '366d', '1.5h', '1month']:
            result = self.cli('record', '--id', 'next.step', '--statement', 'Invalid update', '--ttl', value, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('TTL must', result.stderr)
        self.assertEqual(self.files(), before)

    def test_replacement_errors_explain_same_id_and_root_without_private_disclosure(self):
        self.cli('record', '--id', 'microbastion.next_step', '--statement', 'Paso anterior', '--quiet')
        result = self.cli('record', '--id', 'microbastion.next_step', '--statement', 'Paso nuevo',
                          '--replaces', 'microbastion.next_step', check=False)
        self.assertIn('without --replaces', result.stderr)
        self.assertEqual(record_history(self.root, 'microbastion.next_step')['current_revision'], 1)
        self.cli('record', '--id', 'microbastion.next_step', '--statement', 'Paso nuevo', '--quiet')
        self.assertEqual(record_history(self.root, 'microbastion.next_step')['current_revision'], 2)
        self.record('note.private', 'Private record', sensitivity='private')
        messages = []
        for target in ['note.missing', 'note.private']:
            result = self.cli('record', '--id', 'next.new', '--statement', 'New state', '--replaces', target, check=False)
            self.assertIn('in this project root', result.stderr)
            self.assertIn('search QUERY', result.stderr)
            messages.append(result.stderr)
        self.assertEqual(messages[0], messages[1])

    def test_changed_rules_keep_evidence_warnings_without_hiding_live_task(self):
        start_task(self.root, 'Meta vigente', next_actions=['Paso vigente'])
        for n, name in enumerate(['REGLAS.md', 'CONTEXTO-CLAUDE.md', 'CONTEXTO-CLAUDE.md']):
            p = self.root / name
            p.write_text('original')
            self.record('note.rules'+str(n), 'Fuente anterior '+str(n),
                        type='constraint' if n==0 else 'note', state='verified',
                        evidence=[{'path':name, 'content_hash':sha256_file(p)}])
        for name in ['REGLAS.md', 'CONTEXTO-CLAUDE.md']:
            (self.root / name).write_text('modified')
        before = self.files()
        x = brief(self.root, role='W7')
        self.assertIn('[global] Meta vigente', x['text'])
        self.assertIn('[global] Paso vigente', x['text'])
        self.assertIn('REVISAR VIGENCIA', x['text'])
        self.assertNotIn('Fuente anterior 1', x['text'])
        self.assertFalse(x['essential_complete'])
        findings = run_doctor(self.root)['findings']
        self.assertEqual(len([f for f in findings if f['code']=='stale-evidence']), 3)
        self.assertEqual(self.files(), before)
