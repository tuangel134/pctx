"""Shared lifecycle for CLI, MCP and the local dashboard."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .adapters import TARGETS, sync_adapters
from .architecture import load_architecture, refresh_architecture
from .compile import export_context
from .model import utc_now
from .scan import collect_files, scan_project, git_snapshot
from .storage import cache_dir, init_context, load_manifest, project_lock, sha256_file, write_json_atomic
from .tasks import checkpoint_task, ensure_tasks_file, load_tasks


def validate_workspace(root: Path) -> Path:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Project directory does not exist: {root}")
    # Generated files must never redirect a write outside the selected project.
    targets = [root / ".project-context", *(root / name for name in ("PROJECT_CONTEXT.md", "architecture.md", "TASKS.md", *TARGETS.values()))]
    context = root / ".project-context"
    if context.is_dir() and not context.is_symlink():
        targets.extend(context.rglob("*"))
    for target in targets:
        if target.is_symlink() or (target.exists() and root not in target.resolve().parents):
            raise ValueError(f"Refusing redirected context path: {target}")
    return root


def read_snapshot(root: Path) -> dict[str, Any]:
    path = cache_dir(root) / "snapshot.json"
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not isinstance(value.get("files", {}), dict):
            return {}
        if any(not isinstance(item, dict) for item in value.get("files", {}).values()):
            return {}
        return value
    except (OSError, ValueError):
        return {}  # Only this reconstructible cache may be discarded.


def changes(root: Path) -> dict[str, Any]:
    old_snapshot = read_snapshot(root)
    previous = old_snapshot.get("files", {})
    current = {}
    files = collect_files(root, max_files=10001)
    for path in files[:10000]:
        try:
            current[path.relative_to(root).as_posix()] = sha256_file(path)
        except OSError:
            continue
    added = sorted(set(current) - set(previous))
    removed = sorted(set(previous) - set(current))
    modified = sorted(name for name in set(previous) & set(current) if previous[name].get("sha256") != current[name])
    import hashlib
    fingerprint = hashlib.sha256(json.dumps(current, sort_keys=True).encode()).hexdigest()
    return {"content_digest": fingerprint, "added": added, "modified": modified, "removed": removed,
            "changed": sorted(set(added + modified + removed)), "initialized": bool(old_snapshot),
            "truncated": len(files) > 10000 or bool(old_snapshot.get("truncated"))}


def sync_installed_adapters(root: Path, *, force=False) -> dict[str, Any]:
    if not force and load_manifest(root).get('exports', {}).get('mode', 'auto') == 'manual':
        return {'results': [], 'drift': [], 'deferred': True}
    names = [name for name, path in TARGETS.items() if (root / path).is_file() or (name == "cline" and (root / path / "project-context.md").is_file())]
    return sync_adapters(root, names) if names else {"results": [], "drift": []}


def refresh_project(root: Path, *, initialize: bool = False, max_files: int = 10000, full: bool = False, observed_changes: list[str] | None = None) -> dict[str, Any]:
    root = validate_workspace(root)
    with project_lock(root):
        if initialize:
            init_context(root)
        else:
            load_manifest(root)
        # Validate canonical memory before writing derived output.
        load_tasks(root)
        load_architecture(root)
        delta = changes(root)
        delta["changed"] = sorted(set(delta["changed"] + (observed_changes or [])))
        marker = cache_dir(root) / "refresh.json"
        write_json_atomic(marker, {"status": "running", "started_at": utc_now()})
        try:
            task = load_tasks(root).get("active")
            if task and delta["changed"]:
                checkpoint_task(root, status=task["status"], changed_files=sorted(set(task["changed_files"] + delta["changed"])), capture=False)
            scan = scan_project(root, max_files=max_files, full=full)
            architecture = refresh_architecture(root, full=full)
            ensure_tasks_file(root)
            from .knowledge import build_index
            knowledge = build_index(root)
            target, info = export_context(root)
            if initialize and not (root / "AGENTS.md").exists():
                sync_adapters(root, ["agents"])
            adapters = sync_installed_adapters(root)
            report = {"status": "ready", "updated_at": utc_now(), "scan": scan,
                      "changes": delta, "architecture": architecture, "export": str(target),
                      "tokens": info["approximate_tokens"], "adapters": adapters, "knowledge": knowledge}
            write_json_atomic(marker, report)
            return report
        except Exception as exc:
            write_json_atomic(marker, {"status": "error", "updated_at": utc_now(), "error_type": type(exc).__name__})
            raise


class ProjectWatcher:
    """Polling watcher: bounded scans, no LLM calls and no conversation capture."""
    def __init__(self, root: Path, interval: float = 5):
        if interval < 1:
            raise ValueError("Watch interval must be at least one second")
        self.root = root.resolve()
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.error: str | None = None
        self.last_update: str | None = None

    def tick(self) -> bool:
        with project_lock(self.root):
            delta = changes(self.root)
            saved_git = read_snapshot(self.root).get("git", {})
            current_git = git_snapshot(self.root)
            git_changed = any(saved_git.get(key) != current_git.get(key) for key in ("head", "branch", "remote", "is_git"))
            if not delta["initialized"] or delta["changed"] or git_changed:
                refresh_project(self.root)
                self.last_update = utc_now()
                self.error = None
                return True
        return False

    def _run(self):
        pending, previous_signature = set(), None
        while not self.stop_event.wait(self.interval):
            try:
                delta = changes(self.root)
                current_git = git_snapshot(self.root)
                saved_git = read_snapshot(self.root).get('git', {})
                git_changed = any(saved_git.get(k) != current_git.get(k) for k in ('head','branch','remote','is_git'))
                signature = (tuple(delta['changed']), delta['content_digest'])
                if not delta['initialized'] or git_changed:
                    self.tick(); pending.clear(); previous_signature = None
                elif signature[0] or pending:
                    pending.update(signature[0])
                    # One quiet polling interval groups a burst. Content is rehashed
                    # by refresh, so unchanged path names cannot hide the latest bytes.
                    if previous_signature == signature:
                        refresh_project(self.root, observed_changes=sorted(pending))
                        self.last_update = utc_now(); self.error = None
                        pending.clear(); previous_signature = None
                    else: previous_signature = signature
            except Exception as exc:
                self.error = str(exc)

    def start(self):
        if self.thread and self.thread.is_alive():
            if not self.stop_event.is_set():
                return
            self.thread.join(timeout=10)
            if self.thread.is_alive():
                raise RuntimeError("Watcher is still completing its last refresh; try again shortly")
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="pctx-watch", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)

    def status(self):
        return {"running": bool(self.thread and self.thread.is_alive() and not self.stop_event.is_set()),
                "error": self.error, "last_update": self.last_update, "interval": self.interval}
