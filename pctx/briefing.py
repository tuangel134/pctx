"""Small, stable prompt for a coordinator or a named worker."""
from __future__ import annotations
import re
from .retrieval import visible_records
from .tasks import load_tasks
from .security import secret_matches


def matches(record, role):
    if role is None: return True
    role = role.casefold()
    if record.get('roles'):
        return role in [x.casefold() for x in record['roles']]
    item = record.get('checklist', record)
    coordination = record.get('coordination', {})
    text = str(coordination.get('session_id', '')) + ' ' + str(coordination.get('task_id', '')) + ' ' + ' '.join(str(item.get(k, '')) for k in ('id', 'owner', 'title')) + ' ' + record.get('id', '') + ' ' + record.get('scope', '') + ' ' + ' '.join(str(t) for t in record.get('tags', []))
    return bool(re.search(r'(?<![a-z0-9])'+re.escape(role)+r'(?![a-z0-9])',text.casefold()))


def shared(record):
    """Unassigned records are project context, not a worker assignment."""
    item = record.get('checklist', record)
    if record.get('roles') or item.get('owner') or 'coordination' in record:
        return False
    labels = ' '.join(str(record.get(k, '')) for k in ('id', 'scope')) + ' ' + ' '.join(record.get('tags', []))
    labels += ' ' + item.get('title', '')
    return not re.search(r'(?<![a-z0-9])w\d+(?![a-z0-9])', labels.casefold())


def brief(root, *, budget=800, role=None):
    if isinstance(budget, bool) or not isinstance(budget, int) or not 128 <= budget <= 100000:
        raise ValueError('brief budget must be 128..100000 approximate tokens')
    if role is not None and (not isinstance(role, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',role)):
        raise ValueError('Invalid worker role')
    records = visible_records(root)
    valid = [r for r in records if r['state'] != 'stale']
    chosen = [r for r in valid if matches(r,role) or shared(r)]
    def display(record, text):
        return ('[global] ' if role is not None and not matches(record, role) else '') + text
    def global_text(text):
        return ('[global] ' if role is not None else '') + text
    from .planning import _records, _views
    plans = _views(root,_records(root))
    work = [r for r in plans.values() if r['status'] not in {'done','verified','cancelled'} and (role is None or matches(r,role))]
    work.sort(key=lambda r:(r['status'] != 'in_progress', r['kind']=='goal',r['id']))
    trace = load_tasks(root).get('active')
    handoff = next((r for r in valid if r['id']=='work.handoff'),None)
    source = trace or handoff or {}
    global_work = [r for r in plans.values() if shared(r) and r['parent'] is None and r['status'] not in {'done','verified','cancelled'}]
    if role is not None and work:
        objective = work[0]['title']
    elif trace:
        objective = global_text(trace['title'])
    elif role is None and work:
        objective = work[0]['title']
    elif source.get('objective'):
        objective = global_text(source['objective'])
    else:
        objective = global_text(global_work[0]['title']) if global_work else None
    specific_steps = [r['statement'] for r in chosen if r['type']=='next_action' and role is not None and matches(r,role)]
    if role is not None and not specific_steps and work:
        specific_steps = [c['text'] for c in work[0]['criteria'] if c['id'] not in work[0]['current_passed_criteria']][:2]
    next_steps = specific_steps + [global_text(x) for x in source.get('next_actions',[])]
    next_steps += [display(r,r['statement']) for r in chosen if r['type']=='next_action' and not (role is not None and matches(r,role))]
    if not next_steps and work:
        next_steps = [c['text'] for c in work[0]['criteria'] if c['id'] not in work[0]['current_passed_criteria']][:2]
    constraints = [r for r in records if r['type']=='constraint' and (matches(r,role) or shared(r))]
    issues = [r for r in chosen if r['type']=='issue']
    issues.sort(key=lambda r:not matches(r,role))
    blockers = [r['title']+': '+r['reason'] for r in work if r['status']=='blocked']
    blockers += [display(r,'['+r['state']+'] '+r['statement']) for r in issues]
    blockers += [global_text(x) for x in source.get('blockers',[])]
    leases = sorted([r['coordination'] for r in chosen if 'coordination' in r],key=lambda r:r['renewed_at'],reverse=True)
    changes = [r['summary'] + ' ['+', '.join(r['paths'])+']' for r in leases if r['summary']][:3]
    changes += [global_text(x) for x in source.get('changed_files',[])][:6]
    recent = sorted(chosen,key=lambda r:r.get('updated_at',''),reverse=True)
    changes += [display(r,'['+r['state']+'] '+r['statement']) for r in recent if r['type']=='attempt'][:3]
    if not changes:
        changes = [display(r,'Registro actualizado ['+r['type']+'/'+r['state']+']: '+r['statement']) for r in recent if r['type'] in {'next_action','issue','fact','decision','note'} and r.get('origin') != 'scanner' and not r.get('checklist') and not r.get('coordination')][:3]
        if trace:
            changes.insert(0,global_text('Checkpoint de tarea actualizado: '+trace['updated_at']))
    groups = [('Objetivo',[objective] if objective else []),('Siguiente paso',next_steps),('Restricciones',[r['id']+': '+r['statement']+(' [REVISAR VIGENCIA]' if r['state']=='stale' else '') for r in constraints]),('Bloqueos',blockers),('Últimos cambios',changes)]
    role_matched = role is None or bool(work) or any(matches(r,role) and r['type'] not in {'constraint','handoff'} for r in valid)
    omitted, incomplete = 0, not objective or not role_matched or any(r['state']=='stale' for r in constraints)
    normalized = []
    for label, items in groups:
        values = []
        for text in items:
            text = ' '.join(str(text).split())
            if len(text)>600:
                text=text[:597]+'…';omitted+=1
                if label=='Restricciones':incomplete=True
            if text not in values:
                values.append(text)
        normalized.append((label,values))
    def render():
        text = '# PCTX brief'+(' · '+role if role else '')+'\n'
        if role is not None and not role_matched:
            text += 'Sin datos específicos para '+role+'; se muestra contexto global disponible.\n'
        for label,items in normalized:
            text+='\n'+label+':\n'+('\n'.join('- '+x for x in items) if items else '- Sin información vigente registrada.')+'\n'
        return text+f'\nOmitidos: {omitted}. Esenciales: {"INCOMPLETOS; consulta pctx context/plan detail" if incomplete else "completos"}. Tokens aproximados: chars/4.\n'
    while (len(render())+3)//4>budget:
        for label in ['Últimos cambios','Bloqueos','Siguiente paso','Objetivo','Restricciones']:
            items=next(items for name,items in normalized if name==label)
            if items:
                items.pop();omitted+=1
                if label in {'Restricciones','Objetivo','Siguiente paso','Bloqueos'}:incomplete=True
                break
        else:raise ValueError('Brief header exceeds budget')
    text=render()
    if secret_matches(text):raise ValueError('Refusing probable secret in brief')
    return {'text':text,'role':role,'budget':budget,'approximate_tokens':(len(text)+3)//4,'omitted':omitted,'essential_complete':not incomplete,'role_matched':role_matched}
