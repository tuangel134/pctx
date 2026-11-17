"""Authenticated, loopback-only dashboard. No runtime web dependencies."""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
from urllib.parse import parse_qs, urlsplit
import webbrowser
from importlib.resources import files

from .architecture import load_architecture
from .doctor import run_doctor
from .integrations import bridge_prompt, configuration, install_configuration, server_config
from .mcp import handle_request
from .model import utc_now
from .security import secret_matches
from .service import ProjectWatcher, read_snapshot, refresh_project, sync_installed_adapters, validate_workspace
from .storage import load_manifest, load_records, project_lock, safe_relative, sha256_file, upsert_record, write_json_atomic
from .compile import export_context
from .tasks import load_tasks
from .history import payload, validate_history
from .review import review_record


DOCUMENTS = {"PROJECT_CONTEXT.md", "architecture.md", "TASKS.md"}
ASSETS = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}


class Dashboard:
    def __init__(self, registry: Path | None = None):
        self.registry = registry or Path(os.environ.get("PCTX_CONFIG_DIR", str(Path.home() / ".config/pctx")))
        self.projects: dict[str, Path] = {}
        self.watchers: dict[str, ProjectWatcher] = {}
        self.mutex = threading.RLock()
        self.token = secrets.token_urlsafe(32)
        for path in sorted((self.registry / "projects").glob("*.json")):
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
                self.projects[path.stem] = Path(entry["root"])
            except (OSError, ValueError, KeyError, TypeError):
                continue

    def add(self, path: str, initialize: bool = False) -> dict:
        if not path.strip() or not Path(path).expanduser().is_absolute():
            raise ValueError("Choose an absolute project directory")
        root = validate_workspace(Path(path))
        if initialize:
            refresh_project(root, initialize=True)
        else:
            load_manifest(root)
        identity = hashlib.sha256(str(root).encode()).hexdigest()[:16]
        with self.mutex:
            write_json_atomic(self.registry / "projects" / f"{identity}.json", {"root": str(root)})
            self.projects[identity] = root
        return {"id": identity, "root": str(root)}

    def project(self, identity: str) -> Path:
        with self.mutex:
            if identity not in self.projects:
                raise ValueError("Select a registered project first")
            return validate_workspace(self.projects[identity])

    def list_projects(self) -> list[dict]:
        with self.mutex:
            entries = list(self.projects.items())
        result = []
        for identity, root in entries:
            try:
                manifest = load_manifest(root)
                result.append({"id": identity, "root": str(root), "name": manifest["name"], "available": True})
            except (OSError, ValueError, KeyError, TypeError):
                result.append({"id": identity, "root": str(root), "name": root.name, "available": False})
        return result

    def state(self, identity: str) -> dict:
        root = self.project(identity)
        with project_lock(root):
            raw = load_records(root)
            revisions = {r['id']:len(validate_history(r)) for r in raw}
            from .freshness import project
            records = project(root, raw)
            visible = [payload(r) | {'current_revision': revisions[r['id']]} for r in records if "checklist" not in r and "coordination" not in r and r.get("sensitivity") not in {"secret", "private"} and not secret_matches(json.dumps(r))]
            snapshot = read_snapshot(root)
            report_path = root / ".project-context/.cache/refresh.json"
            try:
                report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
                if not isinstance(report, dict):
                    report = {"status": "error", "error_type": "invalid refresh cache"}
            except (OSError, ValueError):
                report = {"status": "error", "error_type": "unreadable refresh cache"}
            with self.mutex:
                watcher = self.watchers.get(identity)
            return {"id": identity, "root": str(root), "manifest": load_manifest(root), "records": visible,
                    "tasks": load_tasks(root), "architecture": load_architecture(root),
                    "scan": {"files": len(snapshot.get("files", {})), "at": snapshot.get("generated_at"), "truncated": snapshot.get("truncated", False)},
                    "refresh": {k: report.get(k) for k in ("status", "updated_at", "error_type")},
                    "watch": watcher.status() if watcher else {"running": False}, "guide": bridge_prompt(root)}

    def action(self, identity: str, action: str, args: dict) -> dict:
        root = self.project(identity)
        if action == "index":
            from .knowledge import build_index
            model = args.get('model')
            if model is not None and not isinstance(model, str):
                raise ValueError('model must be a local directory')
            return build_index(root, model=model)
        if action == "refresh":
            return refresh_project(root)
        if action == "watch":
            with self.mutex:
                previous = self.watchers.get(identity)
                if args.get("enabled"):
                    if not previous:
                        previous = ProjectWatcher(root)
                        self.watchers[identity] = previous
                    previous.start()
                elif previous:
                    previous.stop_event.set()
                return previous.status() if previous else {"running": False}
        if action == "doctor":
            with project_lock(root):
                return run_doctor(root)
        if action == "install":
            return install_configuration(root, args.get("client", "generic"), allow_write=not args.get("read_only", False))
        if action == "probe":
            from .diagnostics import diagnose
            return diagnose(root, allow_write=bool(args.get('allow_write', False)))
        if action in {'backup_create', 'backup_preview', 'backup_restore', 'migration_preview', 'migration_apply'}:
            from .backup import create_backup, preview_restore, restore_backup, migrate_history
            if action == 'backup_create': return create_backup(root)
            if action == 'migration_preview': return migrate_history(root)
            if action == 'migration_apply':
                expected = args.get('expected_state')
                if not isinstance(expected, str): raise ValueError('Preview before applying migration')
                result = migrate_history(root, expected_state=expected)
                refresh_project(root); return result
            path = Path(args.get('path', '')).expanduser()
            if not path.is_absolute(): raise ValueError('Select an absolute backup path')
            if action == 'backup_preview': return preview_restore(root, path)
            if not isinstance(args.get('expected_state'), str): raise ValueError('Preview before restoring')
            result = restore_backup(root, path, args['expected_state'])
            refresh_project(root); return result
        if action == "portable":
            from .portable import build_portable
            return build_portable(root)
        if action == "review":
            with project_lock(root):
                operation = args.get('action') or {'user_asserted': 'confirm', 'superseded': 'supersede'}.get(args.get('state'))
                if not isinstance(args.get('expected_revision'), int):
                    raise ValueError('Inspect the current revision before reviewing')
                saved = review_record(root, args.get('id'), operation,
                    expected_revision=args['expected_revision'], statement=args.get('statement'),
                    replacement_id=args.get('replacement_id'), actor='user')
                export_context(root)
                sync_installed_adapters(root)
                return saved
        allowed = {"pctx_brief", "pctx_verify", "pctx_verify_run", "pctx_import_reports", "pctx_report", "pctx_coordination", "pctx_coordination_update", "pctx_plan", "pctx_plan_update", "pctx_context", "pctx_record_update", "pctx_task_update", "pctx_task_resume", "pctx_architecture_update", "pctx_finish", 'pctx_lookup', 'pctx_expand', 'pctx_neighbors', 'pctx_read', 'pctx_context_report', 'pctx_search', 'pctx_history', 'pctx_record_restore', 'pctx_review_queue', 'pctx_record_review', 'pctx_differences'}
        if action not in allowed:
            raise ValueError("Unknown dashboard action")
        response = handle_request(root, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": action, "arguments": args}}, allow_write=True)
        if response.get("error") or response.get("result", {}).get("isError"):
            message = response.get("result", {}).get("content", [{"text": "Tool failed"}])[0]["text"]
            raise ValueError(message)
        return response["result"]

    def stop(self):
        with self.mutex:
            watchers = list(self.watchers.values())
        for watcher in watchers:
            watcher.stop()


def make_server(app: Dashboard, port: int = 0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, payload, content_type="application/json"):
            data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def authorized(self):
            expected = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != expected:
                self.reply(403, {"error": "Invalid host"})
                return False
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + expected:
                self.reply(403, {"error": "Invalid origin"})
                return False
            if not secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + app.token):
                self.reply(401, {"error": "Open the dashboard using the URL printed by pctx gui"})
                return False
            return True

        def do_GET(self):
            url = urlsplit(self.path)
            if url.path in ASSETS:
                name, mime = ASSETS[url.path]
                self.reply(200, (files("pctx") / "web" / name).read_bytes(), mime)
                return
            if not self.authorized():
                return
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                if url.path == "/api/projects":
                    data = {"projects": app.list_projects()}
                elif url.path == "/api/folders":
                    folder = Path(query.get("path") or str(Path.home())).expanduser().resolve()
                    if not folder.is_dir():
                        raise ValueError("Directory does not exist")
                    entries = sorted((p for p in folder.iterdir() if p.is_dir() and not p.is_symlink() and not p.name.startswith(".")), key=lambda p:p.name.casefold())
                    data = {"path": str(folder), "parent": str(folder.parent), "folders": [{"name": p.name, "path": str(p)} for p in entries[:200]], "truncated": len(entries) > 200}
                elif url.path == "/api/state":
                    data = app.state(query.get("id", ""))
                elif url.path == "/api/config":
                    data = configuration(app.project(query.get("id", "")), query.get("client", "generic"), allow_write=query.get("read_only") != "true")
                elif url.path == "/api/document":
                    name = query.get("name")
                    if name not in DOCUMENTS:
                        raise ValueError("Unknown document")
                    root = app.project(query.get("id", ""))
                    with project_lock(root):
                        text = safe_relative(root, name).read_text(encoding="utf-8")
                        if secret_matches(text):
                            raise ValueError("Document contains a probable secret; run diagnostics")
                        data = {"name": name, "text": text}
                else:
                    self.reply(404, {"error": "Not found"})
                    return
                self.reply(200, data)
            except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
                self.reply(400, {"error": str(exc)})

        def do_POST(self):
            if not self.authorized():
                return
            try:
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ValueError("JSON content required")
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 1_048_576:
                    raise ValueError("Body must be 1 byte to 1 MiB")
                self.connection.settimeout(20)
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("JSON object required")
                if self.path == "/api/projects":
                    result = app.add(str(data.get("path", "")), initialize=data.get("initialize") is True)
                elif self.path == "/api/action":
                    args = data.get("args", {})
                    if not isinstance(args, dict):
                        raise ValueError("Action arguments must be an object")
                    result = app.action(data.get("id", ""), data.get("action", ""), args)
                elif self.path == "/api/shutdown":
                    self.reply(200, {"stopped": True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                else:
                    self.reply(404, {"error": "Not found"})
                    return
                self.reply(200, result)
            except (OSError, ValueError, RuntimeError, TypeError, KeyError, subprocess.TimeoutExpired) as exc:
                self.reply(400, {"error": str(exc)})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def serve_dashboard(root: Path, *, port: int = 0, open_browser: bool = True) -> int:
    app = Dashboard()
    if (root / ".project-context/manifest.json").is_file():
        app.add(str(root))
    server = make_server(app, port)
    url = f"http://127.0.0.1:{server.server_port}/#token={app.token}"
    print(f"PCTX dashboard: {url}\nCtrl+C or 'Apagar panel' stops this panel and its watchers. IDE MCP processes are independent.", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
        server.server_close()
    return 0
