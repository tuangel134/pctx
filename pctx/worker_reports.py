"""Idempotent import and reservation-free writes of worker reports, never instructions."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re

from .model import make_record,safe_record_filename
from .public_paths import resolve
from .security import secret_matches
from .storage import load_records,project_lock,upsert_record,write_text_atomic


def _owns(record,path,section):
    source=record.get('report_source',{})
    if not isinstance(source,dict):return False
    return source.get('path')==path and source.get('section')==section


def _hash(text):return hashlib.sha256(text.encode()).hexdigest()


def sections(text):
    # Code/command blocks are report data, not durable facts or runnable checks.
    text=re.sub(r'(?ms)^\s*```.*?^\s*```\s*$', '',text)
    result=[];seen={};heading='Informe';body=[]
    def emit():
        value='\n'.join(body).strip()
        if not value:return
        n=seen.get(heading,0);seen[heading]=n+1
        key=_hash(heading+'\n'+str(n))[:20]
        result.append({'key':key,'heading':heading,'body':value,'hash':_hash(heading+'\n'+value)})
    for line in text.splitlines():
        if re.match(r'^#{1,4}\s+',line):
            emit();heading=re.sub(r'^#+\s+','',line).strip();body=[]
        else:body.append(line)
    emit()
    if len(result)>128:raise ValueError('Report has more than 128 sections; split it before import')
    return result


def _read(root,relative):
    path=resolve(root,relative)
    if not path.is_file() or path.stat().st_size>262144:
        raise ValueError('Report unavailable or exceeds 256 KiB')
    text=path.read_text(encoding='utf-8')
    if secret_matches(text):raise ValueError('Report contains a probable secret; redact it before importing')
    if '\0' in text:raise ValueError('Report must be text')
    if len(re.findall(r'(?mi)^\s*(?:user|assistant|system)\s*:',text))>=2:
        raise ValueError('Chat transcripts are not worker reports')
    return text


def section_status(root,item,cache=None):
    cache={} if cache is None else cache
    key=('report',item['path'])
    if key not in cache:cache[key]={r['key']:r['hash'] for r in sections(_read(root,item['path']))}
    actual=cache[key].get(item.get('section'))
    return 'current' if actual and actual==item.get('content_hash') else 'changed' if actual else 'missing'


def import_reports(root,*,paths=None,patterns=None,role=None):
    if role is not None and not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',role):raise ValueError('Invalid worker role')
    paths=set(paths or [])
    patterns=patterns or ([] if paths else ['**/HECHO-*.md','**/INTEGRACION-LOG.md'])
    for pattern in patterns:
        if not isinstance(pattern,str) or len(pattern)>500 or pattern.startswith('/') or '..' in Path(pattern).parts or '\\' in pattern:
            raise ValueError('Report glob must stay in project')
        for p in root.glob(pattern):
            paths.add(p.relative_to(root).as_posix())
            if len(paths)>200:raise ValueError('Import at most 200 reports at a time; select fewer files')
    paths=sorted(set(paths))
    if len(paths)>200:raise ValueError('Import at most 200 reports at a time')
    prepared=[];warnings=[]
    # Validate every source before any mutation; a secret/malformed report cannot partially import a batch.
    for relative in paths:
        text=_read(root,relative)
        inferred_role=role or (re.search(r'(?i)(?:^|[^A-Za-z0-9])(W\d+)(?=[^A-Za-z0-9]|$)',relative).group(1).upper() if re.search(r'(?i)(?:^|[^A-Za-z0-9])(W\d+)(?=[^A-Za-z0-9]|$)',relative) else None)
        for row in sections(text):
            heading_role=re.search(r'(?i)(?:^|[^A-Za-z0-9])(W\d+)(?=[^A-Za-z0-9]|$)',row['heading'])
            section_role=(heading_role.group(1).upper() if heading_role and Path(relative).name=='INTEGRACION-LOG.md' else inferred_role) or (heading_role.group(1).upper() if heading_role else None)
            body=row['body']
            if len(body)>3500:
                body=body[:3499]+'…';warnings.append(relative+': section excerpted; read the source for complete coverage')
            kind='issue' if re.search(r'(?i)\b(bug|issue|bloqueo|error|fallo|pendiente|problema)\b',row['heading']) else 'attempt'
            id='report.'+_hash(relative+'\n'+row['key'])[:24]
            record=make_record(record_type=kind,record_id=id,statement=row['heading'][:300]+'\n'+body,state='inferred',origin='worker-report',scope='worker/'+section_role if section_role else 'reports',evidence=[{'kind':'report','path':relative,'section':row['key'],'content_hash':row['hash'],'ref':relative+'#'+row['key']}],roles=[section_role] if section_role else [],stability='stable',report_source={'path':relative,'section':row['key'],'hash':row['hash']})
            prepared.append(record)
            if len(prepared)>1000:raise ValueError('Import at most 1000 sections per batch; select fewer reports')
    result={'files':len(paths),'created':0,'updated':0,'unchanged':0,'ids':[],'warnings':warnings[:20],'warnings_truncated':len(warnings)>20,'warning':'Imported worker assertions remain inferred; no command is executed and no test pass is invented.'}
    with project_lock(root):
        old={r['id']:r for r in load_records(root)}
        for record in prepared:
            previous=old.get(record['id'])
            if (previous and not _owns(previous,record['report_source']['path'],record['report_source']['section'])) or (root/'.project-context/.private/records'/safe_record_filename(record['id'])).exists():
                raise ValueError('Report ID belongs to another record')
            if secret_matches(json.dumps(record,ensure_ascii=False)):raise ValueError('Report contains a probable secret')
        for record in prepared:
            previous=old.get(record['id'])
            if previous and not _owns(previous,record['report_source']['path'],record['report_source']['section']):raise ValueError('Report ID belongs to another record')
            if previous and previous.get('report_source')==record['report_source'] and previous.get('roles')==record['roles']:
                result['unchanged']+=1;continue
            upsert_record(root,record);result['updated' if previous else 'created']+=1;result['ids'].append(record['id'])
    result['ids_truncated']=len(result['ids'])>100
    result['ids']=result['ids'][:100]
    return result


def write_report(root,*,path,text,append=False,expected_hash=None,role=None):
    # This exception permits only report documents; source code never uses this endpoint.
    name=Path(path).name
    if not (re.fullmatch(r'HECHO-[A-Za-z0-9_.-]+\.md',name) or name=='INTEGRACION-LOG.md'):
        raise ValueError('Reservation-free writes are limited to HECHO-*.md or INTEGRACION-LOG.md')
    if not isinstance(text,str) or not text.strip() or len(text.encode())>262144 or secret_matches(text):
        raise ValueError('Report text unavailable, too large or contains a probable secret')
    if role is not None and not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',role):raise ValueError('Invalid worker role')
    if len(re.findall(r'(?mi)^\s*(?:user|assistant|system)\s*:',text))>=2:raise ValueError('Chat transcripts are not worker reports')
    sections(text)
    if name=='INTEGRACION-LOG.md' and role and not re.match(r'^\s*#{1,4}\s+',text):text='## '+role+'\n'+text
    target=resolve(root,path)
    with project_lock(root):
        old=_read(root,path) if target.exists() else ''
        if old and not append and _hash(old)!=expected_hash:
            raise ValueError('Existing report requires expected_hash or append; inspect it before replacing')
        value=(old.rstrip()+'\n\n'+text.strip()+'\n') if append and old and text.strip() not in old else old if append and text.strip() in old else text.rstrip()+'\n'
        if len(value.encode())>262144:raise ValueError('Combined report exceeds 256 KiB')
        known={r['id']:r for r in load_records(root)}
        for section in sections(value):
            id='report.'+_hash(path+'\n'+section['key'])[:24]
            if (id in known and not _owns(known[id],path,section['key'])) or (root/'.project-context/.private/records'/safe_record_filename(id)).exists():
                raise ValueError('Report ID belongs to another record')
        write_text_atomic(target,value)
        imported=import_reports(root,paths=[path],role=role)
        return {'path':path,'content_hash':_hash(value),'changed':old!=value,'import':imported}
