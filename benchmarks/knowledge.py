"""Synthetic handoff retrieval: identical portable fixtures for 0.3 and 0.4.

This measures answers recoverable from tool output, not a real model/client switch.
Costs include task context, query, complete JSON results and up to two expansions.
The legacy full fallback is separately labelled; it loads all public context/docs.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time

compiler_root = Path(os.environ.get('PCTX_BENCHMARK_COMPILER_ROOT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(compiler_root))
from pctx import __version__
from pctx.compile import compile_context, search_records
from pctx.model import make_record
from pctx.storage import init_context, upsert_record


def wire(value): return json.dumps(value, ensure_ascii=False, separators=(',', ':'))
def cost(text): return math.ceil(len(text)/4)


def fixture(root):
    init_context(root, 'handoff-demo')
    (root/'docs').mkdir(); (root/'src').mkdir()
    (root/'src/audio.py').write_text('def route(): return 1\n')
    documents = {
        'docs/access.md': 'Authentication cookie lifetime is thirty minutes. Renew the cookie before expiry. LOGIN_TTL_30.',
        'docs/payments.md': 'Payment reconciliation uses the settlement ledger. Payments must retain the receipt. SETTLEMENT_LEDGER.',
        'docs/retention.md': ('General archive notes. '*300) + '\nQuartz audit retention is six days. QUARTZ_SIX_DAYS.\n' + ('Ordinary storage details. '*50),
        'docs/ship.md': 'Deployment rollback restores the previous artifact after a failed release. Keep a recovery copy. ROLLBACK_PREVIOUS_ARTIFACT.',
        'docs/privacy.md': 'Analytics collects aggregate counters only. Discard personal identifiers at ingestion. AGGREGATES_ONLY.',
        'docs/travel.md': 'Travel vouchers are filed under the annual budget.'}
    for name,text in documents.items(): (root/name).write_text(text)
    records = [
        ('constraint.signed', 'Preserve signed artifacts. SIGNATURES_PRESERVED.', {}),
        ('decision.aurora', 'Aurora checkout must preserve the transaction contract.', {'links':[{'relation':'supports','target':'file:docs/payments.md'}]}),
        ('decision.audio', 'Communication routing selects the active device. ROUTE_ACTIVE_DEVICE.', {'evidence':[{'path':'src/audio.py'}]}),
        ('procedure.recovery', 'Deployment rollback restores the previous artifact. ROLLBACK_PREVIOUS_ARTIFACT.', {}),
        ('decision.long', ('Session compatibility notes. '*300) + '\nAuthentication renewal preserves browser affinity. BROWSER_AFFINITY.', {}),
        ('note.private', 'PRIVATE_BENCHMARK_MARKER', {'sensitivity':'private'}),
        ('decision.old', 'OLD_BENCHMARK_MARKER', {'state':'superseded'}),
    ]
    for i in range(60): records.append((f'note.warehouse.{i}', f'Warehouse shelf {i} is counted daily. Inventory allocation is batched.', {}))
    for rid,text,extra in records:
        upsert_record(root, make_record(record_id=rid,record_type=rid.split('.')[0],statement=text,**extra))
    public_text = '\n'.join(text for rid,text,extra in records if extra.get('sensitivity')!='private' and extra.get('state')!='superseded')
    fingerprint = hashlib.sha256(wire({'docs':documents,'records':records}).encode()).hexdigest()
    return documents,public_text,fingerprint


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['legacy','lexical','hybrid'], default='lexical')
    parser.add_argument('--model')
    parser.add_argument('--output', required=True)
    args=parser.parse_args()
    cases=[
        ('document-exact','authentication cookie lifetime','LOGIN_TTL_30', True),
        ('spanish-alias','autenticación cookie','LOGIN_TTL_30', True),
        ('semantic-spanish','¿Cuánto tarda en caducar el acceso?','LOGIN_TTL_30', False),
        ('semantic-rollback','Undo an unsuccessful rollout','ROLLBACK_PREVIOUS_ARTIFACT', False),
        ('graph-different-vocabulary','Aurora checkout','SETTLEMENT_LEDGER', True),
        ('deep-document','Quartz audit retention','QUARTZ_SIX_DAYS', True),
        ('evidence-path','src/audio.py','ROUTE_ACTIVE_DEVICE', True),
        ('long-memory','authentication renewal browser affinity','BROWSER_AFFINITY', True),
        ('privacy-document','analytics personal identifiers','AGGREGATES_ONLY', True),
        ('semantic-privacy','¿Conservamos datos que identifiquen a cada visitante?','AGGREGATES_ONLY', False),
    ]
    rows=[]
    with tempfile.TemporaryDirectory(prefix='pctx-knowledge-benchmark-') as temporary:
        root=Path(temporary)
        documents,public_text,fingerprint=fixture(root)
        index_report=None
        if args.mode!='legacy':
            from pctx.knowledge import build_index, lookup, expand
            index_report=build_index(root, model=args.model if args.mode=='hybrid' else None)
        for name,query,answer,lexical_required in cases:
            before=time.perf_counter()
            pack,info=compile_context(root,task=query,budget=512)
            output=[]; expansion_count=0
            if args.mode=='legacy':
                result=search_records(root,query)
                output.append(wire(result))
            else:
                result=lookup(root,query,mode=args.mode,model=args.model,limit=4,budget=1600)
                output.append(wire(result))
                if answer not in ''.join(output):
                    for item in result['results'][:2]:
                        output.extend([wire({'reference':item['ref']}), wire(expand(root,item['ref'],budget=1000))])
                        expansion_count+=1
                        if answer in ''.join(output): break
            transmitted=pack+wire({'query':query})+''.join(output)
            found=answer in transmitted
            fallback_cost=None
            if args.mode=='legacy' and not found:
                fallback=public_text+'\n'+'\n'.join(documents.values())
                fallback_cost=cost(transmitted+fallback)
            assert 'PRIVATE_BENCHMARK_MARKER' not in transmitted and 'OLD_BENCHMARK_MARKER' not in transmitted
            assert info['essential_complete'] and 'SIGNATURES_PRESERVED' in pack
            if args.mode=='lexical' and lexical_required: assert found, name
            if args.mode=='hybrid': assert found, name
            rows.append({'case':name,'query':query,'answer_found':found,'lexical_required':lexical_required,
                         'approximate_total_tokens':cost(transmitted),'legacy_full_fallback_tokens':fallback_cost,
                         'expansions':expansion_count,'seconds':round(time.perf_counter()-before,4),
                         'essential_complete':info['essential_complete']})
    report={'version':__version__,'mode':args.mode,'fixture_digest':fingerprint,'scenarios':rows,
            'answers_found':sum(r['answer_found'] for r in rows),'total_scenarios':len(rows),
            'total_tokens':sum(r['approximate_total_tokens'] for r in rows),'index':index_report,
            'method':'Synthetic output coverage; chars/4, includes query + task context + serialized tool results + explicit expansions. No LLM or external client session.'}
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(wire({k:v for k,v in report.items() if k not in {'scenarios','index'}}))

if __name__=='__main__': main()
