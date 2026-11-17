"""Finite local MCP handshake, catalog and read-call diagnostic."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
from . import __version__
from .storage import load_manifest


def diagnose(root: Path, *, allow_write: bool = False, timeout: float = 10, command: list[str] | None = None) -> dict:
    root=root.expanduser().resolve()
    result={'ok':False,'version':__version__,'executable':sys.executable,'root':str(root),
            'requested_mode':'write-enabled' if allow_write else 'read-only',
            'scope':'local process only; IDE, ChatGPT web and other OS sessions are untested'}
    try:
        if not 0 < timeout <= 60:raise ValueError('Timeout must be between 0 and 60 seconds')
        manifest=load_manifest(root)
        result['project_id']=manifest['project_id']
        archive = Path(sys.argv[0])
        runtime = [sys.executable, '-I', str(archive.resolve())] if archive.suffix == '.pyz' and archive.is_file() else [sys.executable, '-m', 'pctx']
        argv=command or runtime + ['--root',str(root),'mcp','serve'] + (['--allow-write'] if allow_write else [])
        requests=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}},
                  {'jsonrpc':'2.0','method':'notifications/initialized'},
                  {'jsonrpc':'2.0','id':2,'method':'tools/list'},
                  {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'pctx_status','arguments':{}}}]
        if not allow_write:
            requests.append({'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'pctx_record_update',
                'arguments':{'type':'note','statement':'Diagnostic must be refused'}}})
        process=subprocess.run(argv,input='\n'.join(json.dumps(r) for r in requests)+'\n',
            text=True,capture_output=True,timeout=timeout,check=False)
        result['process_closed']=True
        if process.returncode:raise ValueError('MCP process exited unsuccessfully')
        messages=[json.loads(line) for line in process.stdout.splitlines() if line.strip()]
        by_id={r.get('id'):r for r in messages}
        if len(messages)!= (3 if allow_write else 4) or any('error' in by_id.get(n,{}) for n in (1,2,3)):
            raise ValueError('MCP returned an invalid response sequence')
        server=by_id[1]['result']['serverInfo'];tools=by_id[2]['result']['tools']
        read=by_id[3]['result']
        if read.get('isError'):raise ValueError('MCP read call failed')
        status=json.loads(read['content'][0]['text'])
        if status['manifest']['project_id']!=manifest['project_id']:raise ValueError('MCP project identity mismatch')
        write_available=any(t['name']=='pctx_record_update' for t in tools)
        if write_available!=allow_write:raise ValueError('Effective write mode differs from the requested mode')
        if server.get('version')!=__version__:raise ValueError('MCP executable version differs from this PCTX version')
        denied = None if allow_write else bool(by_id[4].get('error') or by_id[4].get('result',{}).get('isError'))
        if denied is False:raise ValueError('Read-only server accepted a write')
        result.update(ok=True,server=server,tools=[t['name'] for t in tools],read_call='pctx_status',
                      effective_mode='write-enabled' if write_available else 'read-only',write_rejected=denied)
    except (OSError,ValueError,TypeError,KeyError,subprocess.TimeoutExpired) as exc:
        result['error']=type(exc).__name__
        # Raw output is never echoed; it may come from a misconfigured executable.
        if isinstance(exc,subprocess.TimeoutExpired):result['process_closed']=True
    return result
