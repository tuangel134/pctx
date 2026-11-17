"""Read-only health checks for a PCTX project."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .adapters import sync_adapters
from .architecture import architecture_data_path, load_architecture
from .model import record_digest, normalize_record
from .security import looks_like_instruction_override, secret_matches
from .storage import context_dir, load_manifest, load_records, records_dir, sha256_file, safe_relative
from .tasks import tasks_data_path, load_tasks
from .history import validate_history


def _finding(level: str, code: str, message: str, path: str | None = None) -> dict[str, Any]:
    result = {"level": level, "code": code, "message": message}
    if path:
        result["path"] = path
    return result


def _scan_text(path: Path, relative: str) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    findings: list[dict[str, Any]] = []
    for code in secret_matches(text):
        findings.append(_finding("error", "secret", f"Possible {code} detected; remove the value before exporting.", relative))
    if looks_like_instruction_override(text):
        findings.append(_finding("warn", "untrusted-instruction", "Text resembles an instruction override; it will be treated as untrusted data.", relative))
    return findings


def run_doctor(root: Path) -> dict[str, Any]:
    root = root.resolve()
    findings: list[dict[str, Any]] = []
    cdir = context_dir(root)
    try:
        import sqlite3
    except ImportError:
        findings.append(_finding('error', 'sqlite-fts5', 'Python SQLite FTS5 is required for unified retrieval.'))
    else:
        try:
            with sqlite3.connect(':memory:') as database:
                database.execute('CREATE VIRTUAL TABLE capability USING fts5(text)')
        except sqlite3.Error:
            findings.append(_finding('error', 'sqlite-fts5', 'Python SQLite FTS5 is required for unified retrieval.'))
    try:
        manifest = load_manifest(root)
        if not manifest.get("project_id"):
            findings.append(_finding("error", "manifest-project-id", "manifest.json has no stable project_id."))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        findings.append(_finding("error", "manifest", str(exc)))
        return {"ok": False, "findings": findings, "records": 0, "errors": 1, "warnings": 0}

    for name, loader in (("tasks", load_tasks), ("architecture", load_architecture)):
        try:
            loader(root)
        except (OSError, ValueError, TypeError) as exc:
            findings.append(_finding("error", name + "-parse", str(exc)))
    refresh_path = cdir / ".cache/refresh.json"
    if refresh_path.exists():
        try:
            refresh = json.loads(refresh_path.read_text(encoding="utf-8"))
            if refresh.get("status") != "ready":
                findings.append(_finding("warn", "interrupted-refresh", "Refresh was interrupted or failed; run refresh to rebuild derived views."))
        except (OSError, ValueError, AttributeError):
            findings.append(_finding("warn", "refresh-cache", "Refresh report cache is unreadable; refresh can rebuild it."))

    records = []
    for path in sorted(records_dir(root).glob("*.json")):
        try:
            with path.open(encoding="utf-8") as handle:
                value = json.load(handle)
                if not isinstance(value, dict):
                    raise ValueError("Record must be a JSON object")
                normalize_record(value)
                validate_history(value)
                records.append(value)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            findings.append(_finding("error", "record-parse", f"Cannot parse record: {exc}", path.relative_to(root).as_posix()))
    from .freshness import project
    for live in project(root, [r for r in records if r.get('sensitivity') not in {'private','secret'}]):
        if live['state']=='stale' and live.get('declared_state')=='verified':
            findings.append(_finding('warn','record-validity',live.get('stale_reason','Record needs review'),live['id']))
    ids = [str(item.get("id", "")) for item in records]
    duplicates = sorted({item for item in ids if item and ids.count(item) > 1})
    for duplicate in duplicates:
        findings.append(_finding("error", "duplicate-id", f"Duplicate record ID: {duplicate}"))

    from .freshness import replacement_map
    archived = replacement_map(records)
    for item in records:
        if item.get("sensitivity") == "secret":
            findings.append(_finding("error", "secret-record", f"Record is marked secret and must not be exported: {item.get('id')}"))
        if item['id'] in archived or item.get('state')=='superseded':
            continue  # Historical evidence is retained without demanding current-source review.
        for evidence in item.get("evidence", []) if isinstance(item.get("evidence", []), list) else []:
            relative = evidence.get("path") if isinstance(evidence, dict) else None
            expected = evidence.get("content_hash") if isinstance(evidence, dict) else None
            if not relative or not expected or relative == "." or evidence.get("kind") == "report":
                continue
            try:
                candidate = safe_relative(root, str(relative))
            except ValueError:
                findings.append(_finding("error", "unsafe-evidence", "Evidence path escapes the project", str(item.get("id"))))
                continue
            if not candidate.exists():
                findings.append(_finding("warn", "missing-evidence", f"Evidence path no longer exists: {relative}", str(item.get("id"))))
                continue
            try:
                current = sha256_file(candidate)
            except OSError:
                current = None
            if current != expected and item.get("state") not in {"stale", "superseded"}:
                findings.append(_finding("warn", "stale-evidence", f"Evidence hash changed; record should be rescanned: {item.get('id')}", str(item.get("id"))))

    try:
        from .planning import _records as plan_records, _views as plan_views
        for rid, item in plan_views(root, plan_records(root)).items():
            if item['declared_status'] == 'verified' and item['status'] != 'verified':
                findings.append(_finding('warn', 'checklist-review', 'Checklist verification is outdated: ' + '; '.join(item['warnings']), rid))
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        findings.append(_finding('error', 'checklist-integrity', 'Cannot validate checklist graph/history: ' + str(exc)))

    try:
        from .coordination import active as active_reservations
        for reservation in active_reservations(root):
            if reservation['status'] == 'clock_anomaly':
                findings.append(_finding('warn', 'coordination-clock', 'Clock precedes latest reservation heartbeat; inspect before resuming', reservation['id']))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        findings.append(_finding('error', 'coordination-integrity', str(exc)))

    generated_paths = [
        root / "PROJECT_CONTEXT.md",
        root / "architecture.md",
        root / "TASKS.md",
        cdir / "manifest.json",
        architecture_data_path(root),
        tasks_data_path(root),
    ]
    for path in (root / "architecture.md", root / "TASKS.md"):
        if not path.exists():
            findings.append(_finding("warn", "missing-generated-file", f"Generated continuity file is missing: {path.name}", path.relative_to(root).as_posix()))
    inspect_paths = generated_paths
    inspect_paths.extend(sorted(records_dir(root).glob("*.json")))
    for path in inspect_paths:
        if path.exists():
            findings.extend(_scan_text(path, path.relative_to(root).as_posix()))

    export = root / "PROJECT_CONTEXT.md"
    if not export.exists():
        findings.append(_finding("warn", "missing-export", "PROJECT_CONTEXT.md has not been generated."))
    else:
        try:
            text = export.read_text(encoding="utf-8")
            digest = record_digest(records)
            if f"Record digest: `{digest}`" not in text:
                findings.append(_finding("warn", "export-drift", "PROJECT_CONTEXT.md does not match the current record digest."))
        except OSError as exc:
            findings.append(_finding("error", "export-read", str(exc)))

    try:
        adapter_check = sync_adapters(root, check=True)
        for path in adapter_check["drift"]:
            findings.append(_finding("info", "adapter-drift", f"Managed adapter needs regeneration: {path}", path))
    except (OSError, ValueError) as exc:
        findings.append(_finding("warn", "adapter-check", str(exc)))

    from .compile import scan_coverage
    coverage = scan_coverage(root)
    if coverage['status'] == 'INCOMPLETE':
        findings.append(_finding('warn', 'scan-coverage', 'Last scan coverage is incomplete; inspect snapshot limits and hash errors.'))
    try:
        generated = load_architecture(root).get('generated', {})
    except (OSError, ValueError):
        generated = {}
    limits = generated.get('coverage', {})
    if any(limits.values()):
        findings.append(_finding('info', 'architecture-coverage', 'Architecture is a bounded map; inspect generated coverage for truncated nodes, edges or source reads.'))
    errors = sum(item["level"] == "error" for item in findings)
    warnings = sum(item["level"] == "warn" for item in findings)
    return {
        "ok": errors == 0,
        "errors": errors,
        "warnings": warnings,
        "records": len(records),
        "findings": findings,
    }
