"""Crash-tolerant task continuity files for PCTX."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from .model import utc_now
from .security import secret_matches
from .storage import context_dir, write_json_atomic, write_text_atomic, locked


TASKS_DATA = "TASKS.json"
TASKS_MARK_START = "<!-- pctx:tasks:start -->"
TASKS_MARK_END = "<!-- pctx:tasks:end -->"
STATUSES = {"active", "paused", "blocked", "done", "interrupted"}


def tasks_data_path(root: Path) -> Path:
    return context_dir(root) / "work" / TASKS_DATA


def _default_data() -> dict[str, Any]:
    return {"schema_version": 1, "updated_at": utc_now(), "active": None, "history": []}


def _clean_list(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    return [str(item).strip() for item in values if str(item).strip()]


def _normalize_task(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    task = dict(value)
    task["id"] = str(task.get("id", "task-unknown"))
    task["title"] = str(task.get("title", "Untitled task")).strip() or "Untitled task"
    task["status"] = str(task.get("status", "active")) if str(task.get("status", "active")) in STATUSES else "active"
    for key in ("acceptance", "next_actions", "blockers", "changed_files"):
        task[key] = _clean_list(task.get(key))
    return task


def load_tasks(root: Path) -> dict[str, Any]:
    from .storage import assert_consistent
    assert_consistent(root)
    path = tasks_data_path(root)
    if not path.exists():
        return _default_data()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read task memory; repair {path} before writing: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("history", []), list):
        raise ValueError(f"Invalid task memory: {path}")
    if raw.get("schema_version", 1) != 1 or (raw.get("active") is not None and not isinstance(raw["active"], dict)) or any(not isinstance(item, dict) for item in raw.get("history", [])):
        raise ValueError(f"Invalid task schema or entries: {path}")
    data = _default_data()
    if isinstance(raw, dict):
        data["schema_version"] = raw.get("schema_version", 1)
        data["updated_at"] = raw.get("updated_at", data["updated_at"])
        data["active"] = _normalize_task(raw.get("active"))
        data["history"] = [task for item in raw.get("history", []) if (task := _normalize_task(item)) is not None][-40:]
    return data


def _persist(root: Path, data: dict[str, Any]) -> dict[str, Any]:
    data["updated_at"] = utc_now()
    data["history"] = data.get("history", [])[-40:]
    if secret_matches(json.dumps(data, ensure_ascii=False, sort_keys=True)):
        raise ValueError("PCTX refuses to persist a probable secret in task continuity")
    target = root / "TASKS.md"
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    generated = render_tasks_markdown(root, data)
    if TASKS_MARK_START in existing and TASKS_MARK_END in existing:
        before = existing.split(TASKS_MARK_START, 1)[0].rstrip()
        after = existing.split(TASKS_MARK_END, 1)[1].lstrip()
        generated = (before + "\n\n" if before else "") + generated + ("\n" + after if after else "")
    elif existing.strip():
        generated = existing.rstrip() + "\n\n" + generated
    write_json_atomic(tasks_data_path(root), data)
    write_text_atomic(target, generated)
    return data


def _task_id(title: str, created_at: str) -> str:
    return f"task-{uuid.uuid4().hex[:12]}"


@locked
def start_task(root: Path, title: str, *, acceptance: Any = None, next_actions: Any = None, blockers: Any = None, changed_files: Any = None, origin: str = "mcp") -> dict[str, Any]:
    title = str(title).strip()
    if not title:
        raise ValueError("PCTX task requires a non-empty title")
    data = load_tasks(root)
    if not data.get("active"):
        previous = next((t for t in reversed(data["history"]) if t["title"] == title and t["status"] in {"paused", "blocked", "interrupted"}), None)
        if previous:
            acceptance = previous["acceptance"] if acceptance is None else acceptance
            next_actions = previous["next_actions"] if next_actions is None else next_actions
            blockers = previous["blockers"] if blockers is None else blockers
            changed_files = previous["changed_files"] if changed_files is None else changed_files
    now = utc_now()
    active = data.get("active")
    if active and active.get("title") == title and active.get("status") in {"active", "paused", "blocked"}:
        active["status"] = "active"
        active["updated_at"] = now
        if acceptance is not None:
            active["acceptance"] = _clean_list(acceptance)
        if next_actions is not None:
            active["next_actions"] = _clean_list(next_actions)
        if blockers is not None:
            active["blockers"] = _clean_list(blockers)
        if changed_files is not None:
            active["changed_files"] = _clean_list(changed_files)
        return _persist(root, data)["active"]
    if active:
        active["status"] = "interrupted"
        active["ended_at"] = now
        data["history"].append(active)
    task = {
        "id": _task_id(title, now),
        "title": title,
        "status": "active",
        "acceptance": _clean_list(acceptance),
        "next_actions": _clean_list(next_actions),
        "blockers": _clean_list(blockers),
        "changed_files": _clean_list(changed_files),
        "origin": origin,
        "started_at": now,
        "updated_at": now,
    }
    from .continuity import capture_snapshot
    task['checkpoint_snapshot'] = capture_snapshot(root)
    data["active"] = task
    return _persist(root, data)["active"]


@locked
def resume_task(root: Path, task_id: str | None = None) -> dict[str, Any]:
    data = load_tasks(root)
    candidates = ([data["active"]] if data.get("active") else []) + list(reversed(data["history"]))
    previous = next((task for task in candidates if task["status"] != "done" and (not task_id or task["id"] == task_id)), None)
    if previous is None:
        raise ValueError("No unfinished task matches the requested ID")
    from .continuity import task_differences
    differences = task_differences(root, previous["id"])
    resumed = start_task(root, previous["title"], acceptance=previous["acceptance"], next_actions=previous["next_actions"], blockers=previous["blockers"], changed_files=previous["changed_files"], origin="resume")
    return dict(resumed, resume_differences=differences)


@locked
def checkpoint_task(root: Path, *, title: str | None = None, status: str = "active", acceptance: Any = None, next_actions: Any = None, blockers: Any = None, changed_files: Any = None, capture: bool = True) -> dict[str, Any] | None:
    if status not in STATUSES - {"done", "interrupted"}:
        raise ValueError(f"invalid task status: {status}")
    data = load_tasks(root)
    active = data.get("active")
    if not active:
        if not title:
            return None
        active = start_task(root, title, acceptance=acceptance, next_actions=next_actions, blockers=blockers, changed_files=changed_files)
        data = load_tasks(root)
        active = data.get("active")
    if not active:
        return None
    active["status"] = status
    active["updated_at"] = utc_now()
    if title:
        active["title"] = str(title).strip() or active["title"]
    if acceptance is not None:
        active["acceptance"] = _clean_list(acceptance)
    if next_actions is not None:
        active["next_actions"] = _clean_list(next_actions)
    if blockers is not None:
        active["blockers"] = _clean_list(blockers)
    if changed_files is not None:
        active["changed_files"] = _clean_list(changed_files)
    if capture:
        from .continuity import capture_snapshot
        active['checkpoint_snapshot'] = capture_snapshot(root)
    return _persist(root, data)["active"]


@locked
def finish_task(root: Path, *, title: str, acceptance: Any = None, next_actions: Any = None, blockers: Any = None, changed_files: Any = None) -> dict[str, Any]:
    data = load_tasks(root)
    active = data.get("active")
    if not active:
        start_task(root, title, acceptance=acceptance, next_actions=next_actions, blockers=blockers, changed_files=changed_files)
        data = load_tasks(root)
        active = data["active"]
    if acceptance is not None:
        active["acceptance"] = _clean_list(acceptance)
    if next_actions is not None:
        active["next_actions"] = _clean_list(next_actions)
    if blockers is not None:
        active["blockers"] = _clean_list(blockers)
    if changed_files is not None:
        active["changed_files"] = _clean_list(changed_files)
    active["title"] = str(title).strip() or active["title"]
    active["status"] = "blocked" if active["blockers"] else "paused" if active["next_actions"] else "done"
    from .continuity import capture_snapshot
    active['checkpoint_snapshot'] = capture_snapshot(root)
    active["finished_at"] = utc_now()
    active["updated_at"] = active["finished_at"]
    data["history"].append(active)
    data["history"] = data["history"][-40:]
    data["active"] = None
    _persist(root, data)
    return active


def render_task_summary(root: Path, data: dict[str, Any] | None = None) -> str:
    data = data or load_tasks(root)
    active = data.get("active")
    if not active:
        history = data.get("history", [])
        if history:
            last = history[-1]
            return f"No active task. Last task: `{last.get('title', '')}` ({last.get('status', 'unknown')}). Call `pctx_context` to start or resume a task."
        return "No active task recorded. Call `pctx_context` first in write-enabled mode."
    lines = [f"Active task: `{active.get('title', '')}`", f"Status: `{active.get('status', 'active')}`"]
    if active.get("next_actions"):
        lines.append("Next actions: " + "; ".join(active["next_actions"][:5]))
    if active.get("blockers"):
        lines.append("Blockers: " + "; ".join(active["blockers"][:5]))
    lines.append("If this task remains active, the previous AI session may have stopped before closing it.")
    return "\n".join(lines)


def render_tasks_markdown(root: Path, data: dict[str, Any] | None = None) -> str:
    data = data or load_tasks(root)
    lines = [
        TASKS_MARK_START,
        "# Project tasks",
        "",
        "> Generated by PCTX. An active task is a recovery marker, not a chat transcript.",
        "",
        "## Active task",
        "",
    ]
    active = data.get("active")
    if active:
        lines.extend([f"### {active.get('title', 'Untitled task')}", "", f"- ID: `{active.get('id', '')}`", f"- Status: `{active.get('status', 'active')}`", f"- Started: `{active.get('started_at', '')}`"])
        for label, key in (("Acceptance", "acceptance"), ("Next actions", "next_actions"), ("Blockers", "blockers"), ("Changed files", "changed_files")):
            if active.get(key):
                lines.extend(["", f"**{label}:**", *[f"- {item}" for item in active[key]]])
        lines.extend(["", "> If the process stopped unexpectedly, resume this task with `pctx_context` or `pctx task update`."])
    else:
        lines.append("No active task. The next write-enabled `pctx_context` call will create one.")
    history = data.get("history", [])
    if history:
        lines.extend(["", "## Recent tasks", "", *[f"- `{item.get('status', 'unknown')}` {item.get('title', '')} ({item.get('updated_at', '')})" for item in reversed(history[-12:])]])
    from .planning import brief as plan_brief
    overview = plan_brief(root)
    if overview:
        lines.extend(['', overview])
    lines.extend(["", TASKS_MARK_END, ""])
    return "\n".join(lines)


@locked
def ensure_tasks_file(root: Path) -> dict[str, Any]:
    data = load_tasks(root)
    if not tasks_data_path(root).exists() or not (root / "TASKS.md").exists():
        _persist(root, data)
    else:
        target = root / 'TASKS.md'
        existing = target.read_text(encoding='utf-8')
        if TASKS_MARK_START in existing and TASKS_MARK_END in existing:
            before, tail = existing.split(TASKS_MARK_START, 1)
            _, after = tail.split(TASKS_MARK_END, 1)
            generated = before + render_tasks_markdown(root, data).rstrip('\n') + after
            if generated != existing:
                write_text_atomic(target, generated)
    return data
