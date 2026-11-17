from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from pctx.adapters import sync_adapters
from pctx.architecture import load_architecture
from pctx.compile import compile_context, export_context
from pctx.doctor import run_doctor
from pctx.mcp import handle_request
from pctx.model import make_record
from pctx.scan import scan_project
from pctx.storage import init_context, load_handoff, load_records, safe_relative, upsert_record, write_json_atomic
from pctx.tasks import load_tasks


class PctxTestCase(unittest.TestCase):
    def make_project(self, files: dict[str, str]) -> Path:
        directory = Path(tempfile.mkdtemp(prefix="pctx-test-"))
        for name, content in files.items():
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return directory

    def test_init_scan_and_export_are_portable(self) -> None:
        root = self.make_project({
            "package.json": json.dumps({"name": "demo", "scripts": {"test": "vitest", "build": "vite build"}, "devDependencies": {"typescript": "^5"}}),
            "tsconfig.json": "{}\n",
            "src/main.ts": "export const answer = 42;\n",
        })
        manifest, created = init_context(root)
        self.assertTrue(created)
        result = scan_project(root)
        self.assertEqual(result["files"], 3)
        target, info = export_context(root)
        self.assertEqual(target, root / "PROJECT_CONTEXT.md")
        self.assertGreater(info["approximate_tokens"], 0)
        text = target.read_text(encoding="utf-8")
        self.assertIn("TypeScript", text)
        self.assertIn("npm test", text)
        self.assertIn(manifest["project_id"], text)

    def test_evidence_change_marks_user_record_stale(self) -> None:
        root = self.make_project({"architecture.md": "The API is HTTP.\n"})
        init_context(root)
        record = make_record(
            record_type="fact",
            record_id="fact.api.transport",
            statement="The API uses HTTP.",
            state="verified",
            origin="user",
            evidence=[{"kind": "file", "path": "architecture.md", "content_hash": __import__("pctx.storage", fromlist=["sha256_file"]).sha256_file(root / "architecture.md")}],
        )
        upsert_record(root, record)
        (root / "architecture.md").write_text("The API is HTTPS.\n", encoding="utf-8")
        scan_project(root)
        records = {item["id"]: item for item in load_records(root)}
        self.assertEqual(records["fact.api.transport"]["state"], "stale")

    def test_adapter_preserves_unmanaged_content(self) -> None:
        root = self.make_project({})
        init_context(root)
        (root / "AGENTS.md").write_text("# Team instructions\n\nKeep the release branch protected.\n", encoding="utf-8")
        result = sync_adapters(root, ["agents"])
        self.assertEqual(result["drift"], ["AGENTS.md"])
        result = sync_adapters(root, ["agents"])
        self.assertEqual(result["drift"], [])
        text = (root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("release branch protected", text)
        self.assertIn("pctx:managed:start", text)

    def test_doctor_detects_secret(self) -> None:
        root = self.make_project({})
        init_context(root)
        raw_secret = make_record(
            record_type="note",
            record_id="note.fake-secret",
            statement="api_key=ghp_abcdefghijklmnopqrstuvwxyz0123456789",
            sensitivity="internal",
        )
        # Simulate an imported/corrupted record; normal upsert rejects it.
        write_json_atomic(root / ".project-context" / "records" / "note.fake-secret.json", raw_secret)
        result = run_doctor(root)
        self.assertFalse(result["ok"])
        self.assertTrue(any(item["code"] == "secret" for item in result["findings"]))

    def test_path_traversal_is_rejected(self) -> None:
        root = self.make_project({})
        with self.assertRaises(ValueError):
            safe_relative(root, "../outside.txt")
        with self.assertRaises(ValueError):
            safe_relative(root, "/tmp/outside.txt")

    def test_task_context_reports_relevance_and_budget(self) -> None:
        root = self.make_project({"README.md": "A small service.\n"})
        init_context(root)
        scan_project(root)
        upsert_record(root, make_record(
            record_type="constraint",
            record_id="constraint.no-secrets",
            statement="Never commit secrets or API keys.",
            state="user_asserted",
        ))
        text, info = compile_context(root, task="avoid secrets while fixing the service", budget=1800)
        self.assertLessEqual(info["approximate_tokens"], 1800)
        self.assertIn("constraint.no-secrets", text)

    def test_mcp_is_read_only_by_default(self) -> None:
        root = self.make_project({"README.md": "A service.\n"})
        init_context(root)
        scan_project(root)
        listed = handle_request(root, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertTrue(any(item["name"] == "pctx_context" for item in listed["result"]["tools"]))
        denied = handle_request(root, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "pctx_record_update", "arguments": {"type": "note", "statement": "x"}}})
        self.assertNotIn("pctx_record_update", [item["name"] for item in listed["result"]["tools"]])
        self.assertNotIn("pctx_task_update", [item["name"] for item in listed["result"]["tools"]])
        self.assertNotIn("pctx_architecture_update", [item["name"] for item in listed["result"]["tools"]])
        self.assertTrue(denied["result"]["isError"])

    def test_mcp_write_lifecycle_refreshes_and_saves_handoff(self) -> None:
        root = self.make_project({"package.json": json.dumps({"name": "flow", "scripts": {"test": "pytest"}}), "src/app.py": "print('ok')\n"})
        init_context(root)
        scan_project(root)
        initialized = handle_request(root, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, allow_write=True)
        self.assertIn("pctx_finish", initialized["result"]["instructions"])
        listed = handle_request(root, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, allow_write=True)
        names = [item["name"] for item in listed["result"]["tools"]]
        self.assertTrue({"pctx_context", "pctx_refresh", "pctx_record_update", "pctx_handoff_save", "pctx_finish"}.issubset(names))
        update = handle_request(root, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "pctx_record_update", "arguments": {"type": "decision", "statement": "The service keeps the current test command.", "scope": "build", "evidence": ["package.json"]}}}, allow_write=True)
        self.assertFalse(update["result"]["isError"])
        records = {item["id"]: item for item in load_records(root)}
        self.assertTrue(any(item["type"] == "decision" and item["state"] == "inferred" for item in records.values()))
        (root / "package.json").write_text(json.dumps({"name": "flow", "scripts": {"test": "pytest", "build": "python -m compileall src"}}), encoding="utf-8")
        context = handle_request(root, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "pctx_context", "arguments": {"task": "build the service", "budget": 1800}}}, allow_write=True)
        self.assertFalse(context["result"]["isError"])
        self.assertIn("npm run build", (root / "PROJECT_CONTEXT.md").read_text(encoding="utf-8"))
        finished = handle_request(root, {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "pctx_finish", "arguments": {"objective": "Finish the build change", "acceptance": ["Build command is documented"], "next_actions": ["Run the build"]}}}, allow_write=True)
        self.assertFalse(finished["result"]["isError"])
        self.assertEqual(load_handoff(root)["objective"], "Finish the build change")
        self.assertIn("package.json", load_handoff(root)["changed_files"])
        next_ai = handle_request(root, {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "pctx_context", "arguments": {"task": "resume the build change", "budget": 1800}}})
        self.assertFalse(next_ai["result"]["isError"])
        self.assertIn("Finish the build change", next_ai["result"]["content"][0]["text"])

    def test_mcp_handoff_collects_git_changes_when_not_declared(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not installed")
        root = self.make_project({"README.md": "A service.\n"})
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        init_context(root)
        scan_project(root)
        (root / "src.py").write_text("print('changed')\n", encoding="utf-8")
        finished = handle_request(root, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "pctx_finish", "arguments": {"objective": "Capture the changed workspace"}}}, allow_write=True)
        self.assertFalse(finished["result"]["isError"])
        self.assertIn("src.py", load_handoff(root)["changed_files"])

    def test_mcp_creates_recovery_task_and_mermaid_architecture(self) -> None:
        root = self.make_project({
            "pyproject.toml": "[project]\nname = 'demo'\n",
            "src/app.py": "from src.service import run\n",
            "src/service.py": "def run(): return True\n",
            "tests/test_app.py": "from src.app import run\n",
        })
        init_context(root)
        scan_project(root)
        context = handle_request(root, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "pctx_context", "arguments": {"task": "Implement the service", "budget": 2400}}}, allow_write=True)
        self.assertFalse(context["result"]["isError"])
        self.assertIn("Active task", context["result"]["content"][0]["text"])
        self.assertIn("flowchart LR", (root / "architecture.md").read_text(encoding="utf-8"))
        self.assertIn("component_src", json.dumps(load_architecture(root)))
        self.assertEqual(load_tasks(root)["active"]["title"], "Implement the service")

        architecture = handle_request(root, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "pctx_architecture_update", "arguments": {"nodes": [{"id": "database", "label": "PostgreSQL", "kind": "service"}], "edges": [{"source": "component_src", "target": "database", "label": "queries"}], "notes": ["The service boundary is kept behind the repository layer."]}}}, allow_write=True)
        self.assertFalse(architecture["result"]["isError"])
        architecture_text = (root / "architecture.md").read_text(encoding="utf-8")
        self.assertIn("component_src -->|queries| database", architecture_text)
        self.assertIn("service boundary", architecture_text)

        checkpoint = handle_request(root, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "pctx_task_update", "arguments": {"status": "blocked", "blockers": ["Waiting for the database schema"], "changed_files": ["src/app.py"]}}}, allow_write=True)
        self.assertFalse(checkpoint["result"]["isError"])
        self.assertEqual(load_tasks(root)["active"]["status"], "blocked")
        finished = handle_request(root, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "pctx_finish", "arguments": {"objective": "Implement the service", "next_actions": ["Resume after the schema is available"], "blockers": ["Waiting for the database schema"], "changed_files": ["src/app.py"]}}}, allow_write=True)
        self.assertFalse(finished["result"]["isError"])
        self.assertIsNone(load_tasks(root)["active"])
        self.assertEqual(load_tasks(root)["history"][-1]["status"], "blocked")
        self.assertIn("Task continuity", (root / "PROJECT_CONTEXT.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
