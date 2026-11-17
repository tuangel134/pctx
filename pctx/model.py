"""The small, portable data model used by PCTX.

The canonical on-disk representation is deliberately JSON rather than a
database.  JSON records are easy to inspect, merge, archive and consume from
any language.  Markdown is generated from them for humans and AI tools.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

SCHEMA_VERSION = 1

RECORD_TYPES = {
    "fact",
    "decision",
    "constraint",
    "procedure",
    "issue",
    "attempt",
    "handoff",
    "next_action",
    "unknown",
    "note",
}

RECORD_STATES = {
    "verified",
    "user_asserted",
    "inferred",
    "stale",
    "superseded",
    "unknown",
}

SENSITIVITY_LEVELS = {"public", "internal", "private", "secret"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_record_id(record_type: str, scope: str, statement: str) -> str:
    """Create a deterministic ID when a caller did not provide one."""

    digest = hashlib.sha256(f"{record_type}\n{scope}\n{statement}".encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"[^a-z0-9]+", "-", statement.lower()).strip("-")[:42] or "record"
    return f"{record_type}.{slug}.{digest}"


def safe_record_filename(record_id: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", record_id).strip(".")
    return (value or "record")[:180] + ".json"


def record_digest(records: list[dict[str, Any]]) -> str:
    """Hash records canonically, independent of filesystem order."""

    canonical = [normalize_record(item) for item in records]
    canonical.sort(key=lambda item: item["id"])
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_evidence(item: Any) -> dict[str, Any]:
    if isinstance(item, str):
        return {"ref": item, "kind": "reference"}
    if not isinstance(item, dict):
        return {"ref": str(item), "kind": "reference"}
    result = dict(item)
    result.setdefault("kind", "reference")
    if "ref" not in result:
        result["ref"] = result.get("path", "")
    return result


def normalize_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Apply defaults and reject malformed values without losing extensions."""

    if not isinstance(raw, dict) or raw.get("schema_version", 1) != 1:
        raise ValueError("Unsupported record schema")
    record = dict(raw)
    record_type = str(record.get("type", "note"))
    if record_type not in RECORD_TYPES:
        record_type = "note"
    statement = str(record.get("statement", "")).strip()
    scope = str(record.get("scope", "project")).strip() or "project"
    record["type"] = record_type
    record["scope"] = scope
    record["statement"] = statement
    record.setdefault("id", stable_record_id(record_type, scope, statement))
    record["id"] = str(record["id"])
    state = str(record.get("state", "unknown"))
    record["state"] = state if state in RECORD_STATES else "unknown"
    record.setdefault("origin", "user")
    record.setdefault("stability", "volatile" if record_type in {"issue", "attempt", "handoff", "next_action"} else "stable")
    sensitivity = str(record.get("sensitivity", "internal"))
    record["sensitivity"] = sensitivity if sensitivity in SENSITIVITY_LEVELS else "internal"
    evidence = record.get("evidence", [])
    if not isinstance(evidence, list):
        evidence = [evidence]
    record["evidence"] = [normalize_evidence(item) for item in evidence]
    record.setdefault("created_at", utc_now())
    record.setdefault("updated_at", record["created_at"])
    record.setdefault("tags", [])
    if not isinstance(record["tags"], list):
        record["tags"] = [str(record["tags"])]
    from .freshness import validate_metadata
    validate_metadata(record)
    if "links" in record:
        from .links import validate_links
        record["links"] = validate_links(record["links"])
    if 'checklist' in record:
        from .planning_model import validate_checklist
        if not re.fullmatch(r'plan\.[A-Za-z0-9_-]{1,100}', record['id']) or record['type'] != 'note':
            raise ValueError('Checklist records require a reserved plan ID and note type')
        validate_checklist(record['checklist'])
    elif record['id'].startswith('plan.'):
        raise ValueError('Reserved checklist ID; use pctx plan')
    if 'coordination' in record:
        from .coordination import validate_lease
        if not re.fullmatch(r'coord\.[a-f0-9]{32}', record['id']) or record['type'] != 'note' or 'checklist' in record:
            raise ValueError('Reserved coordination ID/type required')
        if record['sensitivity'] not in {'public', 'internal'} or record['state'] == 'superseded':
            raise ValueError('Coordination records must stay visible in the shared root')
        validate_lease(record['coordination'])
    elif record['id'].startswith('coord.'):
        raise ValueError('Reserved coordination ID; use pctx coordinate')
    return record


def make_record(
    *,
    record_type: str,
    statement: str,
    scope: str = "project",
    state: str = "user_asserted",
    origin: str = "user",
    evidence: list[dict[str, Any]] | None = None,
    record_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    record = {
        "id": record_id or stable_record_id(record_type, scope, statement),
        "type": record_type,
        "scope": scope,
        "statement": statement.strip(),
        "state": state,
        "origin": origin,
        "evidence": evidence or [],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    record.update(extra)
    return normalize_record(record)
