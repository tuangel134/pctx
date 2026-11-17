from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pctx.architecture import load_architecture, update_architecture
from pctx.dashboard import Dashboard, make_server
from pctx.integrations import configuration, install_configuration
from pctx.mcp import handle_request
from pctx.model import make_record, record_digest
from pctx.scan import collect_files, scan_project, git_snapshot
from pctx.service import ProjectWatcher, changes, refresh_project
from pctx.storage import load_records, sha256_file, upsert_record
from pctx.tasks import checkpoint_task, load_tasks, start_task
from pctx.compile import compile_context, search_records
from pctx.portable import build_portable


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pctx-workflow-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project with spaces"
        self.root.mkdir()
        (self.root / "app.py").write_text("answer = 1\n")
        (self.root / "pyproject.toml").write_text('[project]\nname="demo"\nversion="1.0"\n')
        refresh_project(self.root, initialize=True)

    def call(self, name, args, write=True):
        response = handle_request(self.root, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}, allow_write=write)
        self.assertNotIn("error", response)
        self.assertFalse(response["result"]["isError"], response)
        return response["result"]

    def test_watcher_retains_changes_and_marks_evidence_stale(self):
        self.call("pctx_context", {"task": "update app"})
        self.call("pctx_record_update", {"type": "fact", "statement": "Answer is one", "evidence": ["app.py"]})
        watcher = ProjectWatcher(self.root)
        self.assertFalse(watcher.tick())
        (self.root / "app.py").write_text("answer = 2\n")
        self.assertTrue(watcher.tick())
        self.assertFalse(watcher.tick(), "Generated output must not trigger a refresh loop")
        self.assertIn("app.py", load_tasks(self.root)["active"]["changed_files"])
        self.assertEqual(next(r for r in load_records(self.root) if r["statement"] == "Answer is one")["state"], "stale")
        (self.root / "app.py").unlink()
        self.assertTrue(watcher.tick())
        self.assertIn("app.py", load_tasks(self.root)["active"]["changed_files"])

    def test_finish_preserves_omitted_pending_work(self):
        self.call("pctx_context", {"task": "continue"})
        self.call("pctx_task_update", {"next_actions": ["Test on target IDE"], "blockers": ["Client unavailable"]})
        self.call("pctx_finish", {"objective": "continue"})
        task = load_tasks(self.root)["history"][-1]
        self.assertEqual(task["status"], "blocked")
        self.assertEqual(task["next_actions"], ["Test on target IDE"])

    def test_corrupt_canonical_memory_is_not_overwritten(self):
        task_path = self.root / ".project-context/work/TASKS.json"
        task_path.write_text("BROKEN")
        with self.assertRaises(ValueError):
            refresh_project(self.root)
        self.assertEqual(task_path.read_text(), "BROKEN")
        malformed = '{"schema_version":1,"active":[],"history":[]}'
        task_path.write_text(malformed)
        with self.assertRaises(ValueError):
            refresh_project(self.root)
        self.assertEqual(task_path.read_text(), malformed)

    def test_manual_task_notes_survive_checkpoints(self):
        target = self.root / "TASKS.md"
        target.write_text("# Team notes\nPreserve this.\n\n" + target.read_text() + "\nPersonal note.\n")
        start_task(self.root, "task")
        checkpoint_task(self.root, next_actions=["next"])
        self.assertIn("Preserve this.", target.read_text())
        self.assertIn("Personal note.", target.read_text())

    def test_configuration_merge_backup_and_paths_with_spaces(self):
        target = self.root / ".cursor/mcp.json"
        target.parent.mkdir()
        original = '{"mcpServers":{"existing":{"command":"demo"}},"other":42}'
        target.write_text(original)
        result = install_configuration(self.root, "cursor")
        content = json.loads(target.read_text())
        self.assertEqual(content["other"], 42)
        self.assertIn("existing", content["mcpServers"])
        self.assertEqual(Path(result["backup"]).read_text(), original)
        self.assertFalse(install_configuration(self.root, "cursor")["written"])
        config = content["mcpServers"]["pctx"]
        process = subprocess.run([config["command"], *config["args"]], input='{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n', text=True, capture_output=True, cwd=self.temp.name, timeout=15)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("pctx_finish", process.stdout)
        target.write_text("// JSONC configuration")
        with self.assertRaises(ValueError):
            install_configuration(self.root, "cursor")
        self.assertEqual(target.read_text(), "// JSONC configuration")

    def test_mcp_resources_prompts_and_invalid_requests(self):
        for method in ("resources/list", "prompts/list"):
            r = handle_request(self.root, {"jsonrpc": "2.0", "id": 3, "method": method})
            self.assertIn("result", r)
        r = handle_request(self.root, {"jsonrpc": "2.0", "id": 2, "method": "resources/read", "params": {"uri": "pctx://project/context"}})
        self.assertIn("PROJECT_CONTEXT", r["result"]["contents"][0]["text"])
        for request in ([], None, 42, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": []}):
            self.assertIn("error", handle_request(self.root, request))
        response = handle_request(self.root, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertIsNone(response)
        r = handle_request(self.root, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "pctx_context", "arguments": {"task": "", "budget": -1}}}, allow_write=True)
        self.assertTrue(r["result"]["isError"])

    def test_scan_idempotence_and_deleted_commands(self):
        before = record_digest(load_records(self.root))
        scan_project(self.root)
        self.assertEqual(before, record_digest(load_records(self.root)))
        (self.root / "pyproject.toml").unlink()
        scan_project(self.root)
        commands = next(r for r in load_records(self.root) if r["id"] == "procedure.project.commands")
        self.assertEqual(commands["state"], "superseded")

    def test_git_initial_repository_and_exclusions(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / ".env").write_text("SECRET=private")
        (self.root / "private.txt").write_text("excluded")
        (self.root / ".pctxignore").write_text("private.txt\n")
        names = [p.name for p in collect_files(self.root)]
        self.assertNotIn(".env", names)
        self.assertNotIn("private.txt", names)
        self.assertTrue(git_snapshot(self.root)["is_git"])

    def test_concurrent_processes_do_not_drop_task_history(self):
        script = "from pathlib import Path; from pctx.tasks import start_task; import sys; start_task(Path(sys.argv[1]), sys.argv[2])"
        def work(i):
            return subprocess.run([sys.executable, "-c", script, str(self.root), f"work-{i}"], capture_output=True, text=True, timeout=15)
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(work, range(12)))
        self.assertTrue(all(p.returncode == 0 for p in results), [p.stderr for p in results])
        data = load_tasks(self.root)
        self.assertEqual(len({t["title"] for t in data["history"] + [data["active"]]}), 12)

    def test_redirected_context_path_is_rejected(self):
        external = Path(self.temp.name) / "outside"
        external.write_text("preserve")
        (self.root / "TASKS.md").unlink()
        (self.root / "TASKS.md").symlink_to(external)
        with self.assertRaises(ValueError):
            refresh_project(self.root)
        self.assertEqual(external.read_text(), "preserve")

    def test_budget_includes_header_and_private_records_never_leave_memory(self):
        upsert_record(self.root, make_record(record_type="note", statement="Confidential business strategy", sensitivity="private"))
        self.assertTrue(list((self.root / ".project-context/.private/records").glob("*.json")))
        self.assertFalse(any(r["statement"] == "Confidential business strategy" for r in load_records(self.root)))
        for i in range(35):
            upsert_record(self.root, make_record(record_type="decision", statement=f"Decision {i}: " + "important context " * 50))
        for budget in (256, 1000, 1800, 4000):
            text, info = compile_context(self.root, task="review decisions", budget=budget)
            self.assertLessEqual(info["approximate_tokens"], budget)
            self.assertNotIn("Confidential business strategy", text)
            self.assertTrue(info["omitted"])
        full, _ = compile_context(self.root)
        self.assertNotIn("Confidential business strategy", full)
        self.assertFalse(search_records(self.root, "Confidential business strategy"))

    def test_resume_keeps_pending_actions_and_stable_record_ids(self):
        self.call("pctx_context", {"task": "resume test"})
        self.call("pctx_task_update", {"next_actions": ["next step"], "blockers": ["waiting"]})
        self.call("pctx_finish", {"objective": "resume test"})
        self.call("pctx_task_resume", {})
        self.assertEqual(load_tasks(self.root)["active"]["next_actions"], ["next step"])
        self.assertEqual(load_tasks(self.root)["active"]["blockers"], ["waiting"])
        self.call("pctx_record_update", {"id": "decision.api", "type": "decision", "statement": "Version one"})
        self.call("pctx_record_update", {"id": "decision.api", "type": "decision", "statement": "Version two"})
        self.assertEqual([r["statement"] for r in load_records(self.root) if r["id"] == "decision.api"], ["Version two"])

    def test_nested_projects_have_relative_evidence(self):
        nested = self.root / "packages/web"
        nested.mkdir(parents=True)
        (nested / "package.json").write_text(json.dumps({"name": "web", "scripts": {"test": "node --test"}}))
        report = scan_project(self.root)
        self.assertIn("packages/web", report["subprojects"])
        text, _ = compile_context(self.root)
        self.assertIn("Subproject packages/web", text)
        self.assertIn("packages/web/package.json", text)
        self.assertIn("cd packages/web", text)

    def test_portable_archive_runs_without_site_packages(self):
        bundle = build_portable(self.root)
        process = subprocess.run([sys.executable, "-I", bundle["path"], "--root", str(self.root), "call", "pctx_context", "--allow-write", "--args", '{"task":"portable test","budget":1800}'], cwd=self.temp.name, text=True, capture_output=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertFalse(json.loads(process.stdout)["result"]["isError"])
        self.assertEqual(load_tasks(self.root)["active"]["title"], "portable test")

    def test_rejects_invalid_tool_schema_before_writing(self):
        self.call("pctx_context", {"task": "schema test"})
        before = load_tasks(self.root)
        response = handle_request(self.root, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "pctx_task_update", "arguments": {"next_actions": "not a list"}}}, allow_write=True)
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(before, load_tasks(self.root))

    def test_read_only_mcp_does_not_mutate_project(self):
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.call("pctx_context", {"task": "read only"}, write=False)
        after = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_mcp_watch_updates_without_additional_tool_calls(self):
        config = configuration(self.root, "generic")["config"]["mcpServers"]["pctx"]
        proc = subprocess.Popen([config["command"], *config["args"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            (self.root / "app.py").write_text("answer = 9\n")
            expected = sha256_file(self.root / "app.py")
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                snapshot = json.loads((self.root / ".project-context/.cache/snapshot.json").read_text())
                if snapshot["files"]["app.py"]["sha256"] == expected:
                    break
                time.sleep(0.1)
            else:
                self.fail("MCP watcher did not observe the edit")
            proc.communicate(timeout=15)
            self.assertEqual(proc.returncode, 0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()


class DashboardHTTPTests(unittest.TestCase):
    setUp = WorkflowTests.setUp
    def test_http_auth_origin_resources_and_write_flow(self):
        app = Dashboard(Path(self.temp.name) / "registry")
        identity = app.add(str(self.root))["id"]
        server = make_server(app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(app.stop)
        base = f"http://127.0.0.1:{server.server_port}"

        def request(path, body=None, token=None, origin=None):
            headers = {"Authorization": "Bearer " + (app.token if token is None else token), "Content-Type": "application/json"}
            if origin:
                headers["Origin"] = origin
            data = None if body is None else json.dumps(body).encode()
            with urlopen(Request(base + path, data=data, headers=headers), timeout=20) as response:
                return json.load(response)

        with self.assertRaises(HTTPError) as failure:
            request("/api/projects", token="wrong")
        self.assertEqual(failure.exception.code, 401)
        failure.exception.close()
        with self.assertRaises(HTTPError) as failure:
            request("/api/projects", origin="https://external.example")
        self.assertEqual(failure.exception.code, 403)
        failure.exception.close()
        state = request("/api/state?id=" + identity)
        self.assertEqual(state["root"], str(self.root))
        result = request("/api/action", {"id": identity, "action": "pctx_context", "args": {"task": "HTTP integration"}})
        self.assertFalse(result["isError"])
        request("/api/action", {"id": identity, "action": "pctx_record_update", "args": {"type": "fact", "statement": "HTTP client works", "evidence": ["app.py"]}})
        self.assertTrue(request("/api/action", {"id": identity, "action": "probe"})["ok"])
        with self.assertRaises(HTTPError) as failure:
            request("/api/document?id=" + identity + "&name=../outside")
        failure.exception.close()
        request("/api/action", {"id": identity, "action": "pctx_finish", "args": {"objective": "HTTP integration", "next_actions": []}})
        self.assertEqual(load_tasks(self.root)["history"][-1]["status"], "done")


if __name__ == "__main__":
    unittest.main()
