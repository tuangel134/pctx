"""Safe, atomic storage for PCTX records."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterator
import uuid
import threading
from functools import wraps

from .model import SCHEMA_VERSION, normalize_record, safe_record_filename, utc_now
from .security import secret_matches
from .history import HISTORY_FIELD, advance_history, validate_history


CONTEXT_DIRNAME = ".project-context"
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_HELD = threading.local()


def context_dir(root: Path) -> Path:
    return root / CONTEXT_DIRNAME


def records_dir(root: Path) -> Path:
    return context_dir(root) / "records"


def evidence_dir(root: Path) -> Path:
    return context_dir(root) / "evidence"


def cache_dir(root: Path) -> Path:
    return context_dir(root) / ".cache"


def private_dir(root: Path) -> Path:
    return context_dir(root) / ".private"


def safe_relative(root: Path, relative: str) -> Path:
    """Resolve a user path while rejecting traversal and symlink escapes."""

    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"path must stay relative to project root: {relative}")
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"path escapes project root: {relative}")
    return resolved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_text_atomic(path: Path, text: str) -> None:
    if path.is_file() and not path.is_symlink() and path.read_bytes() == text.encode('utf-8'):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = 0o600 if ".private" in path.parts or path.name.endswith(".lock") else 0o644
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def write_json_atomic(path: Path, value: Any) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    write_text_atomic(path, text)


@contextmanager
def project_lock(root: Path, *, allow_recovery: bool = False) -> Iterator[None]:
    """Reentrant per-project thread and process lock, including nested writes."""
    root = root.resolve()
    key = str(root)
    with _LOCKS_GUARD:
        mutex = _LOCKS.setdefault(key, threading.RLock())
    with mutex:
        held = getattr(_HELD, "roots", set())
        if key in held:
            yield
            return
        lock_path = safe_relative(root, ".project-context/.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as handle:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                if not handle.read(1):
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            _HELD.roots = held | {key}
            try:
                if not allow_recovery and (context_dir(root) / '.restore-transaction').exists():
                    raise ValueError('Interrupted restore requires pctx backup recover before writing')
                yield
            finally:
                _HELD.roots = held
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def locked(function):
    @wraps(function)
    def wrapped(root: Path, *args, **kwargs):
        with project_lock(root):
            return function(root, *args, **kwargs)
    return wrapped


def initial_manifest(root: Path, name: str | None = None) -> dict[str, Any]:
    project_name = name or root.name or "project"
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": str(uuid.uuid4()),
        "name": project_name,
        "root": ".",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "privacy": {
            "network": "disabled_by_default",
            "store_transcripts": False,
            "store_secrets": False,
        },
        "budgets": {"bootstrap_tokens": 1800, "task_tokens": 8000},
    }


@locked
def init_context(root: Path, name: str | None = None) -> tuple[dict[str, Any], bool]:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    cdir = context_dir(root)
    manifest_path = cdir / "manifest.json"
    created = not manifest_path.exists()
    cdir.mkdir(parents=True, exist_ok=True)
    for directory in (records_dir(root), evidence_dir(root), cache_dir(root), private_dir(root), cdir / "work", cdir / "archive"):
        directory.mkdir(parents=True, exist_ok=True)
    private_dir(root).chmod(0o700)
    if created:
        write_json_atomic(manifest_path, initial_manifest(root, name))
    private_gitignore = cdir / ".gitignore"
    if not private_gitignore.exists():
        write_text_atomic(private_gitignore, ".cache/\n.private/\n.runtime/\n.lock\n")
    elif ".runtime/" not in private_gitignore.read_text(encoding="utf-8").splitlines():
        write_text_atomic(private_gitignore, private_gitignore.read_text(encoding="utf-8").rstrip() + "\n.runtime/\n")
    if '.restore-transaction/' not in private_gitignore.read_text(encoding='utf-8').splitlines():
        write_text_atomic(private_gitignore, private_gitignore.read_text(encoding='utf-8').rstrip() + '\n.restore-transaction/\n')
    return load_manifest(root), created


def load_manifest(root: Path) -> dict[str, Any]:
    if (context_dir(root) / ".restore-transaction/journal.json").exists():
        raise ValueError("Interrupted restore requires pctx backup recover before reading memory")
    path = context_dir(root) / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"PCTX is not initialized: {path}")
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("manifest.json must contain an object")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported PCTX schema: {value.get('schema_version')}")
    if not isinstance(value.get("project_id"), str) or not value["project_id"]:
        raise ValueError("manifest.json must have a nonempty project_id")
    return value


def save_manifest(root: Path, manifest: dict[str, Any]) -> None:
    manifest = dict(manifest)
    manifest["updated_at"] = utc_now()
    write_json_atomic(context_dir(root) / "manifest.json", manifest)


def assert_consistent(root: Path) -> None:
    if (context_dir(root) / '.restore-transaction/journal.json').exists():
        raise ValueError('Interrupted restore requires pctx backup recover before reading memory')


def load_records(root: Path) -> list[dict[str, Any]]:
    assert_consistent(root)
    directory = records_dir(root)
    if not directory.exists():
        return []
    result: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        with path.open(encoding="utf-8") as handle:
            record = normalize_record(json.load(handle))
            validate_history(record)
            result.append(record)
    result.sort(key=lambda item: item["id"])
    return result


def upsert_record(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_record(record)
    normalized.pop(HISTORY_FIELD, None)  # History is maintained by the storage layer.
    serialized = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    if normalized.get("sensitivity") == "secret" or secret_matches(serialized):
        raise ValueError("PCTX refuses to persist a probable secret in a canonical record")
    filename = safe_record_filename(normalized["id"])
    path = records_dir(root) / filename
    with project_lock(root):
        private_path = private_dir(root) / 'records' / filename
        if normalized.get('sensitivity') == 'private':
            if path.exists():
                raise ValueError('Changing public records to private requires an explicit privacy migration')
            private_dir(root).mkdir(mode=0o700, parents=True, exist_ok=True)
            private_dir(root).chmod(0o700)
            path = private_path
        elif private_path.exists():
            raise ValueError('A private record already uses this ID; publishing requires an explicit privacy migration')
        existing = None
        if path.exists():
            with path.open(encoding="utf-8") as handle:
                existing = normalize_record(json.load(handle))
            validate_history(existing)
        replacements = [x for x in normalized.get('links', []) if x['relation'] == 'replaces']
        previous_replacements = [x for x in (existing or {}).get('links', []) if x['relation'] == 'replaces']
        if replacements or previous_replacements or normalized.get('claim_key'):
            from .replacement import prepare
            normalized = prepare(root, normalized, previous_replacements)
        if existing:
            if existing["id"] != normalized["id"]:
                raise ValueError("Record ID collides with another record filename; choose a distinct ID")
            ignored = {"created_at", "updated_at", HISTORY_FIELD}
            if {k: v for k, v in existing.items() if k not in ignored} == {k: v for k, v in normalized.items() if k not in ignored}:
                return existing
            normalized["created_at"] = existing.get("created_at", normalized["created_at"])
            normalized["updated_at"] = utc_now()
        normalized[HISTORY_FIELD] = advance_history(existing, normalized)
        write_json_atomic(path, normalized)
    return normalized


def write_handoff(root: Path, handoff: dict[str, Any]) -> None:
    if secret_matches(json.dumps(handoff, ensure_ascii=False)):
        raise ValueError("PCTX refuses to persist a probable secret in a handoff")
    write_json_atomic(context_dir(root) / "work" / "HANDOFF.json", handoff)


def load_handoff(root: Path) -> dict[str, Any] | None:
    assert_consistent(root)
    path = context_dir(root) / "work" / "HANDOFF.json"
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)
