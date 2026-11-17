"""Deterministic retrieval benchmark; identical fixtures for baseline and candidate."""
from __future__ import annotations

import argparse
import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import time

compiler_root = Path(os.environ.get('PCTX_BENCHMARK_COMPILER_ROOT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(compiler_root))
from pctx import __version__
from pctx.architecture import refresh_architecture
from pctx.compile import compile_context
from pctx.model import make_record
from pctx.storage import init_context, upsert_record, write_json_atomic
from pctx.tasks import start_task


def run() -> dict:
    scenarios = [
        ('small', 0, 1800, 'fix authentication', False, False),
        ('noise-300', 300, 1800, 'fix authentication', False, False),
        ('noise-1000', 1000, 1800, 'fix authentication', False, False),
        ('spanish', 100, 1800, 'corregir autenticación y sesión', False, False),
        ('evidence-path', 100, 1800, 'repair src/auth.py', False, False),
        ('long-constraint', 30, 512, 'fix authentication', True, False),
        ('minimum', 30, 256, 'fix authentication', False, False),
        ('many-constraints', 30, 512, 'fix authentication', False, True),
        ('roomy', 300, 6000, 'fix authentication', False, False),
        ('many-task-fields', 10, 512, 'fix authentication', False, False),
        ('long-id-unicode', 10, 256, 'revisar sesión', True, False),
    ]
    rows = []
    for name, noise, budget, query, long_rule, many in scenarios:
        with tempfile.TemporaryDirectory(prefix='pctx-recovery-') as temporary:
            root = Path(temporary)
            (root / 'src').mkdir()
            (root / 'src/auth.py').write_text('def session(): return 1\n')
            init_context(root, 'recovery-demo')
            refresh_architecture(root)
            actions = ['Run the session checks', 'Check the cookie policy']
            blockers = ['Waiting for the schema owner']
            if name == 'many-task-fields':
                actions += [f'Check required route {i}' for i in range(20)]
            start_task(root, 'Restore browser authentication', next_actions=actions,
                       blockers=blockers, origin='benchmark')
            statements = {
                'constraint.project.signed': 'Preserve signed release artifacts.',
                'decision.session.cookie': 'Use an HttpOnly cookie for browser sessions.',
            }
            if long_rule:
                statements['constraint.project.signed'] += ' Review the signed release contract.' * 240
            if name == 'long-id-unicode':
                statements['constraint.' + 'ñ' * 220] = 'Respetar la política de publicación.' * 240
            if many:
                for i in range(30):
                    statements[f'constraint.policy.{i:03}'] = f'Preserve policy {i}: ' + 'requires explicit review. ' * 12
            for rid, statement in statements.items():
                upsert_record(root, make_record(
                    record_type=rid.split('.')[0], record_id=rid, statement=statement,
                    scope='project' if rid.startswith('constraint.') else 'session',
                    evidence=[] if rid.startswith('constraint.') else [{'path': 'src/auth.py'}],
                ))
            upsert_record(root, make_record(record_type='decision', record_id='decision.auth.old',
                statement='OBSOLETE_COOKIE_POLICY', state='superseded'))
            upsert_record(root, make_record(record_type='note', record_id='note.private',
                statement='PRIVATE_BUSINESS_MARKER', sensitivity='private'))
            upsert_record(root, make_record(record_type='issue', record_id='issue.session.stale',
                statement='Session retries may fail.', scope='session', state='stale',
                stale_reason='Evidence was changed.', evidence=[{'path': 'src/auth.py'}]))
            # Deterministic imports avoid measuring a thousand fsyncs for fixture setup.
            for i in range(noise):
                write_json_atomic(root / '.project-context/records' / f'noise.{i:04}.json',
                    make_record(record_type='decision', record_id=f'decision.inventory.{i:04}',
                        statement=f'Inventory route {i} uses warehouse batch allocation.', scope='inventory'))
            required = {rid for rid in statements if rid.startswith('constraint.')}
            start = time.perf_counter()
            text, info = compile_context(root, task=query, budget=budget)
            seconds = time.perf_counter() - start
            repeated, repeated_info = compile_context(root, task=query, budget=budget)
            included = {rid for rid, statement in statements.items() if statement.strip() in text and rid in text}
            reported = set(info.get('essential_omitted', []))
            missing = required - included
            continuity_missing = [item for item in [*actions, *blockers] if item not in text]
            task_omissions = info.get('task_omitted', [])
            irrelevance = sum(f'decision.inventory.{i:04}' in text for i in range(noise))
            unsafe = any(marker in text or marker in json.dumps(info) for marker in
                         ('PRIVATE_BUSINESS_MARKER', 'note.private', 'OBSOLETE_COOKIE_POLICY'))
            essential_accounted = missing <= reported and (not continuity_missing or bool(task_omissions))
            complete_honest = not (missing or continuity_missing) or info.get('essential_complete') is False
            rows.append({
                'scenario': name, 'budget': budget, 'approximate_tokens': info['approximate_tokens'],
                'expected_records': len(statements), 'recovered_records': len(included),
                'missing_essential': sorted(missing), 'reported_essential_omissions': sorted(reported),
                'continuity_missing': continuity_missing, 'irrelevant_records': irrelevance,
                'omitted_records': len(info['omitted']), 'seconds': round(seconds, 6),
                'within_budget': info['approximate_tokens'] <= budget,
                'essential_accounted': essential_accounted, 'completeness_honest': complete_honest,
                'deterministic': text == repeated and info == repeated_info, 'private_or_superseded_leak': unsafe,
            })
    return {'compiler_version': __version__, 'compiler_sha256': hashlib.sha256((compiler_root / 'pctx/compile.py').read_bytes()).hexdigest(),
            'compiler_files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((compiler_root / 'pctx').glob('*.py'))},
            'fixture_version': 2, 'scenarios': rows,
            'passed': all(r['within_budget'] and r['essential_accounted'] and r['completeness_honest']
                          and r['deterministic'] and not r['private_or_superseded_leak'] for r in rows)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    parser.add_argument('--assert-pass', action='store_true')
    args = parser.parse_args()
    report = run()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'passed': report['passed'], 'scenarios': len(report['scenarios']),
                      'unreported_essential_cases': sum(not r['essential_accounted'] for r in report['scenarios']),
                      'irrelevant_records': sum(r['irrelevant_records'] for r in report['scenarios'])}))
    return 1 if args.assert_pass and not report['passed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
