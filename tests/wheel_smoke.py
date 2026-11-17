"""Install a built wheel in a clean venv and exercise CLI, MCP and UI assets."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit, parse_qs
from urllib.request import Request, urlopen
import venv


def main():
    wheel = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="pctx-wheel-") as temporary:
        root = Path(temporary)
        environment = root / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / "bin/python"
        subprocess.run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)], cwd=root, check=True, capture_output=True)
        project = root / "demo"
        project.mkdir()
        (project / "README.md").write_text("Clean wheel validation\n")
        command = [str(python), "-m", "pctx", "--root", str(project)]
        for args in (["init"], ["scan"], ["doctor"], ["call", "pctx_context", "--allow-write", "--args", '{"task":"inspect wheel"}'], ["portable"]):
            result = subprocess.run(command + args, cwd=root, check=True, text=True, capture_output=True, timeout=20)
            assert result.returncode == 0
        for value in ('First packaged contract', 'Second packaged contract'):
            subprocess.run(command + ['decision', '--id', 'decision.wheel', '--statement', value],
                           cwd=root, check=True, text=True, capture_output=True, timeout=20)
        history = subprocess.run(command + ['history', '--id', 'decision.wheel', '--revision', '1', '--compare', '2'],
                                 cwd=root, check=True, text=True, capture_output=True, timeout=20)
        assert json.loads(history.stdout)['changes']['statement']['after'] == 'Second packaged contract'
        read = subprocess.run(command + ['read', '--id', 'decision.wheel'],
                              cwd=root, check=True, text=True, capture_output=True, timeout=20)
        assert json.loads(read.stdout)['records'][0]['statement'] == 'Second packaged contract'
        subprocess.run(command + ['call', 'pctx_context_report', '--args', '{"task":"inspect wheel","budget":256}'],
                       cwd=root, check=True, text=True, capture_output=True, timeout=20)
        for args in (['review'], ['differences'], ['scan', '--full', '--json'], ['diagnose'], ['diagnose', '--write-mode'], ['migrate']):
            subprocess.run(command + args, cwd=root, check=True, text=True, capture_output=True, timeout=20)
        for args in (['index'], ['lookup', 'wheel', '--budget', '512'], ['neighbors', 'record:decision.wheel']):
            subprocess.run(command + args, cwd=root, check=True, text=True, capture_output=True, timeout=20)
        found = subprocess.run(command + ['lookup', 'packaged contract', '--budget', '1000'], cwd=root, check=True, text=True, capture_output=True, timeout=20)
        reference = json.loads(found.stdout)['results'][0]['ref']
        subprocess.run(command + ['expand', reference], cwd=root, check=True, capture_output=True, timeout=20)
        unavailable = subprocess.run(command + ['lookup', 'anything', '--mode', 'hybrid'], cwd=root, capture_output=True, text=True, timeout=20)
        assert unavailable.returncode != 0 and 'explicit local model' in unavailable.stderr
        for args in (['plan','create','--id','plan.wheel','--title','Packaged checklist','--difficulty','easy','--difficulty-reason','Isolated acceptance check','--criteria','Package works'],
                     ['plan','list','--difficulty','easy','--ready','--budget','512'],
                     ['call','pctx_plan','--args','{"action":"detail","id":"plan.wheel"}'],
                     ['call','pctx_plan_update','--allow-write','--args','{"action":"status","id":"plan.wheel","expected_revision":1,"status":"done"}']):
            subprocess.run(command + args, cwd=root, check=True, text=True, capture_output=True, timeout=20)
        backup = root / 'wheel-backup.zip'
        subprocess.run(command + ['backup', 'create', '--output', str(backup)], cwd=root, check=True, capture_output=True, timeout=20)
        preview = subprocess.run(command + ['backup', 'restore', str(backup)], cwd=root, check=True, text=True, capture_output=True, timeout=20)
        assert json.loads(preview.stdout)['expected_state']
        # Rebuild after new records and exercise new modules from the isolated archive.
        subprocess.run(command + ['portable'], cwd=root, check=True, capture_output=True, timeout=20)
        archive = project / '.project-context/.runtime/pctx.pyz'
        portable = subprocess.run([str(python), '-I', str(archive), '--root', str(project), 'history', '--id', 'decision.wheel'],
                                  cwd=root, check=True, text=True, capture_output=True, timeout=20)
        assert json.loads(portable.stdout)['current_revision'] == 2
        for args in (['review'], ['differences'], ['diagnose'], ['migrate'], ['lookup', 'wheel', '--budget', '512'], ['expand', reference], ['neighbors', 'record:decision.wheel']):
            subprocess.run([str(python), '-I', str(archive), '--root', str(project)] + args, cwd=root, check=True, text=True, capture_output=True, timeout=20)
        for args in (['plan','detail','--id','plan.wheel'], ['plan','history','--id','plan.wheel'],
                     ['call','pctx_plan','--args','{"action":"summary"}']):
            subprocess.run([str(python), '-I', str(archive), '--root', str(project)] + args, cwd=root, check=True, text=True, capture_output=True, timeout=20)
        subprocess.run(command + ['plan','status','--id','plan.wheel','--expected-revision','2','--status','pending'], cwd=root, check=True, text=True, capture_output=True, timeout=20)
        lease = subprocess.run([str(python), '-I', str(archive), '--root', str(project), 'coordinate', 'claim', '--session-id', 'Portable AI', '--task-id', 'plan.wheel', '--path', 'src/new-module.py'], cwd=root, check=True, text=True, capture_output=True, timeout=20)
        lease = json.loads(lease.stdout)
        response = subprocess.run(command + ['call', 'pctx_coordination', '--args', json.dumps({'action':'detail','id':lease['id']})], cwd=root, check=True, text=True, capture_output=True, timeout=20)
        assert 'Portable AI' in response.stdout
        subprocess.run(command + ['coordinate','release','--id',lease['id'],'--session-id','Portable AI','--expected-revision','1','--summary','Portable worker handed off packaged task'], cwd=root, check=True, text=True, capture_output=True, timeout=20)
        import shlex
        subprocess.run(command + ['task','update','--next-action','Shared packaged next step','--blocker','Shared packaged blocker'],cwd=root,check=True,capture_output=True,timeout=20)
        for runner in [command,[str(python),'-I',str(archive),'--root',str(project)]]:
            brief_result = subprocess.run(runner + ['brief','--role','W7','--budget','800'], cwd=root, check=True, text=True, capture_output=True, timeout=20)
            assert len(brief_result.stdout) <= 3200 and 'Últimos cambios:' in brief_result.stdout
            assert '[global] Shared packaged next step' in brief_result.stdout
            assert '[global] Shared packaged blocker' in brief_result.stdout
        for id in ['note.old','note.new']:
            saved = subprocess.run(command + ['record','--id',id,'--statement','Packaged current state','--claim-key','packaged.status','--ttl','1d','--quiet'], cwd=root, check=True, text=True, capture_output=True, timeout=20)
            assert saved.stdout == ''
        search = subprocess.run(command + ['search','Packaged current state','--json'], cwd=root, check=True, text=True, capture_output=True, timeout=20)
        assert all(row['id'] != 'note.old' for row in json.loads(search.stdout))
        check_argv = shlex.join([str(python),'-c','print("2/2")'])
        subprocess.run(command + ['record','--id','fact.packaged-check','--type','fact','--statement','Packaged check 2/2','--check-command',check_argv,'--quiet'], cwd=root, check=True, text=True, capture_output=True, timeout=20)
        checked = subprocess.run([str(python),'-I',str(archive),'--root',str(project),'verify','--id','fact.packaged-check','--run','--expected-revision','1'], cwd=root, check=True, text=True, capture_output=True, timeout=20)
        assert json.loads(checked.stdout)['state'] == 'verified'
        report = subprocess.run(command + ['report','--path','.delegacion/HECHO-W4.md','--text','# W4\nPackaged worker report','--role','W4'], cwd=root, check=True, text=True, capture_output=True, timeout=20)
        assert json.loads(report.stdout)['import']['created'] == 1
        repeated = subprocess.run(command + ['import-reports','--path','.delegacion/HECHO-W4.md'], cwd=root, check=True, text=True, capture_output=True, timeout=20)
        assert json.loads(repeated.stdout)['unchanged'] == 1
        subprocess.run(command + ['export','--policy','manual'], cwd=root, check=True, text=True, capture_output=True, timeout=20)
        import os
        process = subprocess.Popen(command + ["gui", "--no-browser"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env={**os.environ, "PCTX_CONFIG_DIR": str(root / "config")})
        try:
            line = process.stdout.readline().strip()
            url = urlsplit(line.split("PCTX dashboard: ", 1)[1])
            base = f"{url.scheme}://{url.netloc}"
            token = parse_qs(url.fragment)["token"][0]
            for asset in ("/", "/style.css", "/app.js"):
                with urlopen(base + asset, timeout=10) as response:
                    assert response.status == 200 and len(response.read()) > 100
            request = Request(base + "/api/projects", headers={"Authorization": "Bearer " + token})
            with urlopen(request, timeout=10) as response:
                assert json.load(response)["projects"][0]["root"] == str(project)
            request = Request(base + "/api/shutdown", data=b"{}", headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
            with urlopen(request, timeout=10) as response:
                assert json.load(response)["stopped"]
            process.communicate(timeout=15)
            assert process.returncode == 0
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
    print("wheel smoke: PASS (clean venv, CLI, MCP, public expansion, history, isolated zipapp, UI assets, shutdown)")


if __name__ == "__main__":
    main()
