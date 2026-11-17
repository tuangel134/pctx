"""Atomic replacement intent; old values remain in portable history."""
from __future__ import annotations
from collections import deque


def prepare(root, record, previous):
    from .storage import load_records
    records = {r['id']: r for r in load_records(root)}
    links = record.get('links', [])
    links += [x for x in previous if x not in links]
    key = record.get('claim_key')
    if key and record['state'] != 'superseded' and record.get('sensitivity') not in {'private', 'secret'}:
        from .freshness import replacement_map
        archived = replacement_map(list(records.values()))
        for old in records.values():
            if old['id'] != record['id'] and old.get('claim_key') == key and old['scope'] == record['scope'] and old.get('sensitivity') not in {'private','secret'} and old['id'] not in archived and old['state'] != 'superseded':
                link = {'relation':'replaces','target':'record:'+old['id']}
                if link not in links: links.append(link)
    for link in links:
        if link['relation'] != 'replaces': continue
        if not link['target'].startswith('record:'):
            raise ValueError('replaces must target a record')
        target = link['target'][7:]
        old = records.get(target)
        if target == record['id']:
            raise ValueError('replaces cannot target its own --id; update the same --id without --replaces (history is kept), or use a new --id with --replaces OLD_ID')
        if old is None or old.get('sensitivity') in {'private','secret'}:
            raise ValueError('Replacement target unavailable in this project root; find a visible OLD_ID with pctx --root PATH search QUERY --json. To update the same record, use --id ID without --replaces')
        if record.get('sensitivity') in {'private','secret'} or old.get('origin') == 'scanner' or target.startswith(('plan.','coord.','work.','fact.project.','procedure.project.')):
            raise ValueError('Managed/private records require their dedicated lifecycle')
    record['links'] = sorted(links,key=lambda x:(x['relation'],x['target']))
    records[record['id']] = record
    edges={id:set(x['target'][7:] for x in r.get('links',[]) if x['relation']=='replaces' and x['target'].startswith('record:')) for id,r in records.items()}
    waiting={id:0 for id in edges}
    for targets in edges.values():
        for target in targets:
            if target in waiting: waiting[target]+=1
    queue=deque(id for id,n in waiting.items() if n==0);seen=0
    while queue:
        id=queue.popleft();seen+=1
        for target in edges[id]:
            if target in waiting:
                waiting[target]-=1
                if waiting[target]==0:queue.append(target)
    if seen!=len(edges): raise ValueError('Replacement cycle; update the current record or use a new ID')
    return record
