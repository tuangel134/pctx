"""Compact, text-first architecture maps for PCTX."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .model import utc_now
from .scan import collect_files
from .security import secret_matches
from .storage import context_dir, write_json_atomic, write_text_atomic, locked


ARCHITECTURE_DATA = "architecture.json"
ARCHITECTURE_MARK_START = "<!-- pctx:architecture:start -->"
ARCHITECTURE_MARK_END = "<!-- pctx:architecture:end -->"
MANIFEST_NAMES = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Makefile",
}
SOURCE_EXTENSIONS = {".c", ".cpp", ".go", ".java", ".js", ".jsx", ".kt", ".py", ".rs", ".ts", ".tsx"}


def architecture_data_path(root: Path) -> Path:
    return context_dir(root) / ARCHITECTURE_DATA


def _default_data() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "updated_at": utc_now(),
        "generated": {"nodes": [], "edges": []},
        "custom": {"nodes": [], "edges": [], "notes": []},
    }


def _normalize_data(value: Any) -> dict[str, Any]:
    data = _default_data()
    if isinstance(value, dict):
        data.update({key: value[key] for key in ("schema_version", "updated_at") if key in value})
        for section in ("generated", "custom"):
            if isinstance(value.get(section), dict):
                data[section].update(value[section])
    for section in ("generated", "custom"):
        data[section]["nodes"] = [item for item in data[section].get("nodes", []) if isinstance(item, dict)]
        data[section]["edges"] = [item for item in data[section].get("edges", []) if isinstance(item, dict)]
    data["custom"]["notes"] = [str(item) for item in data["custom"].get("notes", []) if str(item).strip()]
    return data


def load_architecture(root: Path) -> dict[str, Any]:
    from .storage import assert_consistent
    assert_consistent(root)
    path = architecture_data_path(root)
    if not path.exists():
        return _default_data()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError("Architecture must be a schema-version-1 object")
        for section in ("generated", "custom"):
            if not isinstance(value.get(section), dict):
                raise ValueError("Architecture sections must be objects")
            for field in ("nodes", "edges"):
                if not isinstance(value[section].get(field), list):
                    raise ValueError("Architecture nodes and edges must be lists")
                if any(not isinstance(item, dict) for item in value[section][field]):
                    raise ValueError("Architecture nodes and edges must contain objects")
        if not isinstance(value["custom"].get("notes", []), list):
            raise ValueError("Architecture notes must be a list")
        return _normalize_data(value)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read architecture memory; repair {path} before writing: {exc}") from exc


def _node(node_id: str, label: str, kind: str) -> dict[str, str]:
    return {"id": node_id, "label": label[:120], "kind": kind[:40]}


def _edge(source: str, target: str, label: str) -> dict[str, str]:
    return {"source": source, "target": target, "label": label[:80]}


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")[:42] or "node"


def _top_level(relative: str) -> str:
    return relative.split("/", 1)[0]


def _relative_import_targets(relative: str, text: str) -> list[str]:
    targets: list[str] = []
    if relative.endswith(".py"):
        for match in re.finditer(r"^\s*(?:from|import)\s+([A-Za-z_][\w.]*)", text, re.MULTILINE):
            targets.append(match.group(1).split(".", 1)[0])
    for match in re.finditer(r"(?:from\s+|require\(\s*)['\"](\.{1,2}/[^'\"]+)['\"]", text):
        raw = match.group(1).replace("\\", "/")
        parts = [part for part in raw.split("/") if part not in {"", ".", ".."}]
        if parts:
            targets.append(parts[0])
    if relative.endswith(".rs"):
        for match in re.finditer(r"\buse\s+crate::([A-Za-z_][\w]*)", text):
            targets.append(match.group(1))
    return targets


def _module_key(relative: str) -> str:
    without_suffix = relative.rsplit(".", 1)[0]
    parts = without_suffix.split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _python_import_targets(module_key: str, text: str) -> list[str]:
    targets: list[str] = []
    package = module_key.split(".")[:-1]
    for match in re.finditer(r"^\s*from\s+(\.*)([A-Za-z_][\w.]*)\s+import\s+", text, re.MULTILINE):
        dots = len(match.group(1))
        base = list(package)
        for _ in range(max(0, dots - 1)):
            if base:
                base.pop()
        targets.append(".".join(base + match.group(2).split(".")))
    for match in re.finditer(r"^\s*import\s+([A-Za-z_][\w.]*)", text, re.MULTILINE):
        targets.append(match.group(1))
    return targets


def _build_generated(root: Path, *, max_nodes: int = 64, max_edges: int = 120, full: bool = False) -> dict[str, list[dict[str, str]]]:
    from .incremental import AnalysisCache, config_digest, digest
    from .storage import sha256_file
    analysis = AnalysisCache(root, full=full, namespace='imports')
    config = config_digest(root)
    candidates = collect_files(root, max_files=10001)
    files = candidates[:10000]
    limited, errors = [], []
    relative_files = {path.relative_to(root).as_posix(): path for path in files}
    nodes: list[dict[str, str]] = [_node("project", root.name, "project")]
    edges: list[dict[str, str]] = []
    component_names: set[str] = set()

    for relative in sorted(relative_files):
        if relative in MANIFEST_NAMES:
            manifest_id = f"file_{_slug(relative)}"
            nodes.append(_node(manifest_id, relative, "manifest"))
            edges.append(_edge("project", manifest_id, "configures"))

    for relative, path in sorted(relative_files.items()):
        top = _top_level(relative)
        if "/" not in relative:
            if path.suffix.lower() not in SOURCE_EXTENSIONS:
                continue
        elif path.suffix.lower() not in SOURCE_EXTENSIONS and top != "tests":
            continue
        component_names.add(top)

    component_ids = {name: f"component_{_slug(name)}" for name in sorted(component_names)}
    for name, component_id in component_ids.items():
        is_directory = (root / name).is_dir()
        nodes.append(_node(component_id, f"{name}/" if is_directory else name, "component" if is_directory else "file"))
        edges.append(_edge("project", component_id, "contains"))
        for manifest in MANIFEST_NAMES:
            manifest_id = f"file_{_slug(manifest)}"
            if any(item["id"] == manifest_id for item in nodes):
                edges.append(_edge(manifest_id, component_id, "defines"))

    module_files = {
        _module_key(relative): (relative, path)
        for relative, path in sorted(relative_files.items())
        if path.suffix.lower() in SOURCE_EXTENSIONS and "/" in relative
    }
    module_ids = {key: f"module_{_slug(key)}" for key in module_files}
    for key, (relative, _path) in sorted(module_files.items()):
        module_id = module_ids[key]
        nodes.append(_node(module_id, relative, "module"))
        component_id = component_ids.get(_top_level(relative))
        if component_id:
            edges.append(_edge(component_id, module_id, "contains"))

    for relative, path in sorted(relative_files.items()):
        source_component = component_ids.get(_top_level(relative))
        if not source_component or path.suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        module_key = _module_key(relative) if "/" in relative else ""
        source_module = module_ids.get(module_key)
        try:
            size = path.stat().st_size
            if size > 128 * 1024: limited.append(relative)
            fingerprint = digest([sha256_file(path), config, module_key])
            def parse():
                with path.open('r', encoding='utf-8', errors='replace') as handle:
                    text = handle.read(128 * 1024)
                return {'python': _python_import_targets(module_key, text) if source_module and relative.endswith('.py') else [],
                        'relative': _relative_import_targets(relative, text)}
            imports = analysis.get(relative, fingerprint, parse)
        except OSError:
            errors.append(relative); continue
        if source_module and relative.endswith(".py"):
            for imported in imports['python']:
                target_module = module_ids.get(imported)
                if target_module and target_module != source_module:
                    edges.append(_edge(source_module, target_module, "imports"))
        for imported in imports["relative"]:
            target_name = imported if imported in component_ids else imported.split(".", 1)[0]
            target_component = component_ids.get(target_name)
            if target_component and target_component != source_component:
                edges.append(_edge(source_component, target_component, "imports"))

    unique_nodes: list[dict[str, str]] = []
    seen_nodes: set[str] = set()
    for item in nodes:
        if item["id"] not in seen_nodes:
            unique_nodes.append(item)
            seen_nodes.add(item["id"])
    unique_edges: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for item in edges:
        key = (item["source"], item["target"], item["label"])
        if key not in seen_edges:
            unique_edges.append(item)
            seen_edges.add(key)
    analysis.save()
    return {"nodes": unique_nodes[:max_nodes], "edges": unique_edges[:max_edges],
            'coverage': {'files_truncated': len(candidates) > 10000, 'nodes_truncated': len(unique_nodes) > max_nodes,
                         'edges_truncated': len(unique_edges) > max_edges, 'size_limited': limited, 'unreadable': errors},
            'analysis': analysis.stats()}


def _merge_managed(existing: str, block: str) -> str:
    if ARCHITECTURE_MARK_START in existing and ARCHITECTURE_MARK_END in existing:
        before = existing.split(ARCHITECTURE_MARK_START, 1)[0].rstrip()
        after = existing.split(ARCHITECTURE_MARK_END, 1)[1].lstrip()
        return (before + "\n\n" if before else "") + block.rstrip() + ("\n\n" + after if after else "\n")
    if not existing.strip():
        return block
    return existing.rstrip() + "\n\n" + block


def _escape_label(value: str) -> str:
    return str(value).replace('"', "'").replace("[", "(").replace("]", ")").replace("|", "/").replace("\n", " ").strip()[:120]


def render_architecture(root: Path, data: dict[str, Any] | None = None, *, max_nodes: int = 64, max_edges: int = 120, full: bool = False) -> str:
    data = _normalize_data(data or load_architecture(root))
    nodes = data["generated"]["nodes"] + data["custom"]["nodes"]
    edges = data["generated"]["edges"] + data["custom"]["edges"]
    node_map: dict[str, dict[str, str]] = {}
    priority = {"project": 0, "manifest": 1, "component": 2, "service": 3, "module": 4, "custom": 5}
    ordered_nodes = sorted(nodes, key=lambda item: (priority.get(str(item.get("kind", "custom")), 6), str(item.get("id", ""))))[:max_nodes]
    for item in ordered_nodes:
        if item.get("id"):
            node_map[str(item["id"])] = item
    lines = [
        ARCHITECTURE_MARK_START,
        "# Architecture map",
        "",
        "> Generated by PCTX from static project structure and recorded connections. Keep durable manual notes outside this managed block.",
        "",
        "```mermaid",
        "flowchart LR",
    ]
    for node_id, item in sorted(node_map.items()):
        lines.append(f'    {node_id}["{_escape_label(item.get("label", node_id))}"]')
    seen_edges: set[tuple[str, str, str]] = set()
    for item in edges:
        source = str(item.get("source", ""))
        target = str(item.get("target", ""))
        if source not in node_map or target not in node_map:
            continue
        label = _escape_label(item.get("label", "connects"))
        key = (source, target, label)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        lines.append(f"    {source} -->|{label}| {target}")
        if len(seen_edges) >= max_edges:
            break
    lines.extend(["```", "", "**Legend:** `configures`, `defines`, `contains` and `imports` are static relations; custom relations are recorded by the user or AI."])
    notes = data["custom"].get("notes", [])
    if notes:
        lines.extend(["", "## Durable connection notes", "", *[f"- {note}" for note in notes]])
    lines.extend([ARCHITECTURE_MARK_END, ""])
    return "\n".join(lines)


@locked
def refresh_architecture(root: Path, *, full: bool = False) -> dict[str, Any]:
    data = load_architecture(root)
    data["generated"] = _build_generated(root, full=full)
    data["updated_at"] = utc_now()
    if secret_matches(json.dumps(data, ensure_ascii=False, sort_keys=True)):
        raise ValueError("PCTX refuses to persist a probable secret in architecture data")
    write_json_atomic(architecture_data_path(root), data)
    target = root / "architecture.md"
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    write_text_atomic(target, _merge_managed(existing, render_architecture(root, data)))
    return {"file": str(target), "nodes": len(data["generated"]["nodes"]) + len(data["custom"]["nodes"]), "edges": len(data["generated"]["edges"]) + len(data["custom"]["edges"]), "updated_at": data["updated_at"], "coverage": data["generated"].get("coverage", {}), "analysis": data["generated"].get("analysis", {})}


@locked
def update_architecture(root: Path, *, nodes: list[dict[str, Any]] | None = None, edges: list[dict[str, Any]] | None = None, notes: list[str] | None = None) -> dict[str, Any]:
    data = load_architecture(root)
    custom_nodes = {str(item.get("id")): item for item in data["custom"]["nodes"] if item.get("id")}
    for item in nodes or []:
        if not isinstance(item, dict):
            raise ValueError("architecture nodes must be objects")
        node_id = str(item.get("id", ""))
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,48}", node_id):
            raise ValueError(f"invalid architecture node id: {node_id}")
        label = str(item.get("label", node_id)).replace("\n", " ").strip()
        custom_nodes[node_id] = _node(node_id, label, str(item.get("kind", "custom")))
    custom_edges = {(str(item.get("source", "")), str(item.get("target", "")), str(item.get("label", "connects"))): item for item in data["custom"]["edges"]}
    for item in edges or []:
        if not isinstance(item, dict):
            raise ValueError("architecture edges must be objects")
        source = str(item.get("source", ""))
        target = str(item.get("target", ""))
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,48}", source) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,48}", target):
            raise ValueError("invalid architecture edge endpoint")
        label = str(item.get("label", "connects")).replace("\n", " ").strip() or "connects"
        custom_edges[(source, target, label)] = _edge(source, target, label)
    data["custom"]["nodes"] = list(custom_nodes.values())[:80]
    data["custom"]["edges"] = list(custom_edges.values())[:160]
    existing_notes = [str(item) for item in data["custom"].get("notes", [])]
    for note in notes or []:
        value = str(note).replace("\n", " ").strip()
        if value and value not in existing_notes:
            existing_notes.append(value[:240])
    data["custom"]["notes"] = existing_notes[-40:]
    data["updated_at"] = utc_now()
    if secret_matches(json.dumps(data, ensure_ascii=False, sort_keys=True)):
        raise ValueError("PCTX refuses to persist a probable secret in architecture data")
    write_json_atomic(architecture_data_path(root), data)
    target = root / "architecture.md"
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    write_text_atomic(target, _merge_managed(existing, render_architecture(root, data)))
    return {"file": str(target), "nodes": len(data["generated"]["nodes"]) + len(data["custom"]["nodes"]), "edges": len(data["generated"]["edges"]) + len(data["custom"]["edges"]), "updated_at": data["updated_at"]}
