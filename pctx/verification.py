"""Explicit, bounded local checks. Preview/read operations never run a command."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time
import uuid
import re
from .history import payload,validate_history
from .model import utc_now
from .storage import load_records,load_manifest,project_lock,upsert_record
from .security import secret_matches
from .freshness import evidence_status,workspace_digest,replacement_map,timestamp


def _record(root,id):
    records=load_records(root)
    record=next((r for r in records if r['id']==id and r.get('sensitivity') not in {'private','secret'}),None)
    if record is None or secret_matches(json.dumps(record,ensure_ascii=False)):
        raise ValueError('Check record unavailable')
    if record['id'].startswith(('plan.','coord.','work.','fact.project.','procedure.project.')) or record.get('origin')=='scanner':
        raise ValueError('Use a normal record for command checks; managed records have their own lifecycle')
    if record['state']=='superseded' or id in replacement_map(records):raise ValueError('Record superseded; inspect its replacement before running checks')
    if not record.get('check'):raise ValueError('No check command configured for this record')
    return record


def _execute(root,check):
    started=time.monotonic()
    result={'run_id':uuid.uuid4().hex,'at':utc_now(),'argv':check['argv'],'timeout':check['timeout'],'check_sha256':hashlib.sha256(json.dumps(check,sort_keys=True).encode()).hexdigest(),'timed_out':False,'output_limit':65536}
    digest=hashlib.sha256();total=0;captured=0;tail=b''
    try:
        process=subprocess.Popen(check['argv'],cwd=root,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
    except OSError as exc:
        return result|{'finished_at':utc_now(),'exit_code':None,'launch_error':type(exc).__name__,'output_sha256':digest.hexdigest(),'output_bytes_hashed':0,'output_truncated':False,'seconds':round(time.monotonic()-started,3)}
    selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ)
    def kill():
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    try:
        while selector.get_map():
            if time.monotonic()-started>=check['timeout']:
                result['timed_out']=True;kill();break
            for key,_ in selector.select(timeout=min(.1,max(.01,check['timeout']-(time.monotonic()-started)))):
                data=os.read(key.fd,8192)
                if not data:selector.unregister(key.fileobj);continue
                tail=(tail+data)[-8192:]
                total+=len(data);piece=data[:max(0,65536-captured)]
                digest.update(piece);captured+=len(piece)
        try:process.wait(timeout=max(.01,check['timeout']-(time.monotonic()-started)))
        except subprocess.TimeoutExpired:result['timed_out']=True;kill();process.wait(timeout=5)
    finally:
        selector.close();process.stdout.close()
        if process.poll() is None:kill();process.wait(timeout=5)
    text=tail.decode('utf-8',errors='replace')
    ratio=re.search(r'(?m)^\s*(\d+)\s*/\s*(\d+)(?:\s+(?:tests|pruebas|passed|OK|pass))?\s*$',text)
    unittest=re.search(r'Ran (\d+) tests?',text)
    pytest=re.search(r'(\d+) passed',text)
    if ratio: result['observed_counts']={'passed':int(ratio[1]),'total':int(ratio[2]),'format':'ratio'}
    elif unittest and re.search(r'(?m)^OK\s*$',text): result['observed_counts']={'passed':int(unittest[1]),'total':int(unittest[1]),'format':'unittest'}
    elif pytest:
        other=sum(int(m[0]) for m in re.findall(r'(\d+) (?:failed|skipped|errors?|xfailed|xpassed|deselected)',text))
        result['observed_counts']={'passed':int(pytest[1]),'total':int(pytest[1])+other,'format':'pytest'}
    return result|{'finished_at':utc_now(),'exit_code':process.returncode,'output_sha256':digest.hexdigest(),'output_bytes_hashed':captured,'output_truncated':total>captured,'seconds':round(time.monotonic()-started,3)}


def verify(root:Path,id:str,*,execute=False,expected_revision=None):
    root=root.resolve()
    with project_lock(root):
        record=_record(root,id);revision=len(validate_history(record));check=record['check']
        if not execute:
            return {'id':id,'check':check,'current_revision':revision,'executed':False,'instruction':'Use verify --run --expected-revision N to execute this exact saved command.'}
        if isinstance(expected_revision,bool) or expected_revision!=revision:
            raise ValueError('Check record changed; inspect the command and supply expected_revision')
        if secret_matches(json.dumps(check)):raise ValueError('Check arguments contain a probable secret')
        project_id=load_manifest(root)['project_id']
    # A check may invoke PCTX: release every coordinator lock before starting it.
    before=workspace_digest(root)
    result=_execute(root,check)
    with project_lock(root):
        current=_record(root,id)
        if load_manifest(root)['project_id']!=project_id or len(validate_history(current))!=revision:
            raise ValueError('Check executed but record changed meanwhile; result was not attached. Inspect and run again.')
        record=payload(current)
        evidence=[e for e in record.get('evidence',[]) if e.get('kind')!='workspace']
        checked=evidence_status(root,evidence)
        passed=result['exit_code']==0 and not result['timed_out'] and all(e['status'] in {'current','unverified'} for e in checked)
        if record.get('expires_at') and timestamp(record['expires_at'])<=time.time():passed=False
        claimed=re.search(r'\b(\d+)\s*/\s*(\d+)\b',record['statement'])
        if claimed:
            observed=result.get('observed_counts',{})
            if observed.get('passed')!=int(claimed[1]) or observed.get('total')!=int(claimed[2]): passed=False
        record['verification']=result
        if passed:
            try:
                after=workspace_digest(root)
                if after!=before:passed=False
                else:evidence.append({'kind':'workspace','ref':'workspace-at-check','content_hash':after})
            except (OSError,ValueError):passed=False
        record.update(evidence=evidence,state='verified' if passed else 'stale')
        if passed:record.pop('stale_reason',None);record.pop('stale_at',None)
        else:record.update(stale_reason='Check failed/timed out, claim counts or source changed, evidence is outdated, or fixed expiry elapsed',stale_at=utc_now())
        saved=upsert_record(root,record)
        return {'id':id,'state':saved['state'],'executed':True,'current_revision':len(validate_history(saved)),'result':result}
