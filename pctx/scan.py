"""Deterministic, static repository inspection for PCTX."""

from __future__ import annotations

from collections import Counter
import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess
import shlex
from typing import Any

from .model import make_record, normalize_record, utc_now
from .storage import cache_dir, load_records, sha256_file, write_json_atomic, upsert_record, locked, safe_relative


DEFAULT_IGNORED_DIRS = {
    ".git",
    ".project-context",
    "node_modules",
    "target",
    "dist",
    "build",
    "out",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "coverage",
    ".gradle",
    ".idea",
    ".vscode",
}

MANIFEST_NAMES = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Dockerfile",
    "Makefile",
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
}

GENERATED_CONTEXT_FILES = {
    "PROJECT_CONTEXT.md",
    "architecture.md",
    "TASKS.md",
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".cursorrules",
    ".windsurfrules",
    ".clinerules",
    "CONVENTIONS.md",
}


def _is_context_output(relative: str) -> bool:
    normalized = relative.replace(os.sep, "/")
    return normalized == ".project-context" or normalized.startswith(".project-context/") or normalized in GENERATED_CONTEXT_FILES or normalized == ".github/copilot-instructions.md" or normalized == ".cursor/rules/project-context.mdc"


def run_git(root: Path, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.rstrip("\n")


def git_snapshot(root: Path) -> dict[str, Any]:
    head = run_git(root, ["rev-parse", "HEAD"])
    branch = run_git(root, ["branch", "--show-current"])
    remote = _sanitize_remote(run_git(root, ["remote", "get-url", "origin"]))
    status = run_git(root, ["status", "--porcelain=v1"])
    return {
        "is_git": run_git(root, ["rev-parse", "--is-inside-work-tree"]) == "true",
        "head": head,
        "branch": branch or "(detached)",
        "remote": remote,
        "dirty": bool(status),
        "status": status or "",
        "status_hash": _text_hash(status or ""),
    }


def _sanitize_remote(remote: str | None) -> str | None:
    if not remote:
        return remote
    if "://" in remote:
        scheme, rest = remote.split("://", 1)
        host = rest.split("/", 1)[0]
        if "@" in host:
            rest = rest.split("@", 1)[1]
        return f"{scheme}://{rest}"
    return remote


def _text_hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _load_gitignore(root: Path) -> list[str]:
    path = root / ".gitignore"
    if not path.exists():
        return []
    try:
        return [
            line.strip()
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    except OSError:
        return []


def _excluded(relative: str) -> bool:
    path = Path(relative)
    return (_is_context_output(relative) or any(part in DEFAULT_IGNORED_DIRS or part.endswith(".egg-info") for part in path.parts)
            or path.name == ".env" or path.name.startswith(".env.")
            or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".pyc"}
            or path.name in {"id_rsa", "id_ed25519"})


def _ignored_by_patterns(relative: str, patterns: list[str]) -> bool:
    normalized = relative.replace(os.sep, "/")
    basename = normalized.rsplit("/", 1)[-1]
    ignored = False
    for raw in patterns:
        pattern = raw.strip()
        if not pattern:
            continue
        negated = pattern.startswith("!")
        if negated:
            pattern = pattern[1:]
        pattern = pattern.lstrip("/")
        matched = fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(basename, pattern.rstrip("/"))
        if pattern.endswith("/"):
            directory = pattern.rstrip("/")
            matched = matched or normalized.startswith(directory + "/") or ("/" not in directory and directory in normalized.split("/")[:-1])
        if matched:
            ignored = not negated
    return ignored


def collect_files(root: Path, max_files: int = 10000) -> list[Path]:
    """Collect safe, relative files without following directory symlinks."""

    root = root.resolve()
    patterns = _load_gitignore(root)
    ignore_file = root / ".pctxignore"
    if ignore_file.is_file():
        patterns += [line.strip() for line in ignore_file.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    tracked = run_git(root, ["ls-files", "-z", "-co", "--exclude-standard"])
    if tracked is not None and tracked.strip():
        result = []
        for raw in sorted(set(tracked.split("\0"))):
            if not raw:
                continue
            if _excluded(raw) or _ignored_by_patterns(raw, patterns):
                continue
            path = root / raw
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                resolved = path.resolve()
                if root not in resolved.parents and resolved != root:
                    continue
                result.append(path)
            except OSError:
                continue
        return sorted(result, key=lambda item: item.as_posix())[:max_files]

    result: list[Path] = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        dir_path = Path(directory)
        relative_dir = dir_path.relative_to(root).as_posix() if dir_path != root else ""
        dirnames[:] = [
            name
            for name in dirnames
            if name not in DEFAULT_IGNORED_DIRS and not name.endswith(".egg-info")
            and not _ignored_by_patterns(f"{relative_dir}/{name}".strip("/"), patterns)
        ]
        for filename in filenames:
            path = dir_path / filename
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or _excluded(relative) or _ignored_by_patterns(relative, patterns):
                continue
            try:
                if path.is_file():
                    result.append(path)
            except OSError:
                continue
            if len(result) >= max_files:
                return sorted(result, key=lambda item: item.as_posix())
    return sorted(result, key=lambda item: item.as_posix())


def _read_text(path: Path, limit: int = 2 * 1024 * 1024) -> str:
    if path.is_symlink():
        return ""
    try:
        with path.open("rb") as handle:
            data = handle.read(limit)
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def _json_file(path: Path) -> dict[str, Any] | None:
    if path.is_symlink():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _evidence(root: Path, relative: str, *, symbol: str | None = None) -> dict[str, Any]:
    path = root / relative
    item: dict[str, Any] = {"kind": "file", "path": relative}
    if symbol:
        item["symbol"] = symbol
    if path.is_symlink():
        return item
    try:
        item["content_hash"] = sha256_file(path)
        item["size"] = path.stat().st_size
    except OSError:
        item["content_hash"] = None
    return item


def _package_info(root: Path) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    facts: list[str] = []
    commands: list[str] = []
    evidence: list[dict[str, Any]] = []
    package_path = root / "package.json"
    package = _json_file(package_path)
    if package is not None:
        evidence.append(_evidence(root, "package.json"))
        name = package.get("name")
        if name:
            facts.append(f"Node project name: {name}")
        deps = {}
        deps.update(package.get("dependencies") or {})
        deps.update(package.get("devDependencies") or {})
        if "typescript" in deps or (root / "tsconfig.json").exists():
            facts.append("Language: TypeScript")
        else:
            facts.append("Language: JavaScript")
        frameworks = [
            ("next", "Next.js"),
            ("react", "React"),
            ("vue", "Vue"),
            ("svelte", "Svelte"),
            ("@nestjs/core", "NestJS"),
            ("express", "Express"),
            ("fastapi", "FastAPI"),
        ]
        detected = [label for key, label in frameworks if key in deps]
        if detected:
            facts.append("Frameworks: " + ", ".join(detected))
        manager = package.get("packageManager")
        if manager:
            facts.append(f"Package manager: {str(manager).split('@', 1)[0]}")
        else:
            for lock, label in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "Yarn"), ("bun.lockb", "Bun"), ("package-lock.json", "npm")):
                if (root / lock).exists():
                    facts.append(f"Package manager: {label}")
                    break
        scripts = package.get("scripts") or {}
        for name in ("install", "dev", "build", "test", "lint", "start", "typecheck"):
            if name in scripts:
                prefix = "npm" if not manager else str(manager).split('@', 1)[0]
                command = f"{prefix} {name}" if name in {"test", "start"} else f"{prefix} run {name}"
                commands.append(command)
    return facts, commands, evidence


def _python_info(root: Path) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    facts: list[str] = []
    commands: list[str] = []
    evidence: list[dict[str, Any]] = []
    pyproject = root / "pyproject.toml"
    requirements = root / "requirements.txt"
    if pyproject.exists():
        text = _read_text(pyproject)
        evidence.append(_evidence(root, "pyproject.toml"))
        facts.append("Language: Python")
        if "fastapi" in text.lower():
            facts.append("Framework: FastAPI")
        elif "django" in text.lower():
            facts.append("Framework: Django")
        elif "flask" in text.lower():
            facts.append("Framework: Flask")
        manager = "uv" if (root / "uv.lock").exists() else "poetry" if (root / "poetry.lock").exists() else "pip"
        facts.append(f"Package manager: {manager}")
        commands.extend({"uv": ["uv sync"], "poetry": ["poetry install"], "pip": ["python -m pip install -e ."]}[manager])
        if "pytest" in text.lower():
            commands.append("pytest")
        else:
            tests = root / "tests"
            for candidate in sorted(tests.glob("test*.py"))[:20]:
                if not candidate.is_symlink() and re.search(r"(?:import unittest|from unittest import)", _read_text(candidate, 8192)):
                    commands.append("python -m unittest discover -s tests")
                    evidence.append(_evidence(root, candidate.relative_to(root).as_posix()))
                    break
    elif requirements.exists():
        evidence.append(_evidence(root, "requirements.txt"))
        facts.append("Language: Python")
        facts.append("Package manager: pip")
        commands.append("python -m pip install -r requirements.txt")
        if "pytest" in _read_text(requirements).lower():
            commands.append("pytest")
    return facts, commands, evidence


def _other_info(root: Path) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    facts: list[str] = []
    commands: list[str] = []
    evidence: list[dict[str, Any]] = []
    cargo = root / "Cargo.toml"
    if cargo.exists():
        text = _read_text(cargo)
        evidence.append(_evidence(root, "Cargo.toml"))
        facts.append("Language: Rust")
        match = re.search(r'^\s*name\s*=\s*["\']([^"\']+)', text, re.MULTILINE)
        if match:
            facts.append(f"Rust package: {match.group(1)}")
        commands.extend(["cargo build", "cargo test", "cargo clippy"])
    go_mod = root / "go.mod"
    if go_mod.exists():
        evidence.append(_evidence(root, "go.mod"))
        facts.append("Language: Go")
        commands.extend(["go build ./...", "go test ./...", "go vet ./..."])
    for name in ("Dockerfile", "docker-compose.yml", "docker-compose.yaml"):
        if (root / name).exists():
            evidence.append(_evidence(root, name))
            facts.append(f"Container configuration: {name}")
    if (root / "Makefile").exists():
        evidence.append(_evidence(root, "Makefile"))
        facts.append("Build automation: Makefile")
    return facts, commands, evidence


def _top_level_layout(root: Path, files: list[Path]) -> str:
    counts: Counter[str] = Counter()
    for path in files:
        relative = path.relative_to(root).as_posix()
        counts[relative.split("/", 1)[0]] += 1
    entries = [f"{name}{'/' if (root / name).is_dir() else ''} ({count} files)" for name, count in sorted(counts.items())]
    return "\n".join(entries[:80]) or "(no readable files found)"


def _mark_stale_records(root: Path, records: list[dict[str, Any]]) -> list[str]:
    changed: list[str] = []
    from .freshness import project
    effective = {r['id']: r for r in project(root, [r for r in records if r.get('sensitivity') not in {'private', 'secret'}])}
    for record in records:
        if 'coordination' in record or record.get("origin") == "scanner" or record.get("state") in {"superseded", "stale"}:
            continue
        current_state = effective.get(record['id'], {})
        if current_state.get('state') == 'stale':
            updated = dict(record, state='stale', stale_reason=current_state.get('stale_reason', 'Evidence changed'), stale_at=utc_now())
            upsert_record(root, updated); changed.append(record['id']); continue
        if current_state.get('state') == 'superseded':
            continue
        for evidence in record.get("evidence", []):
            relative = evidence.get("path")
            expected = evidence.get("content_hash")
            if not relative or not expected or evidence.get('kind') == 'report':
                continue
            try:
                path = safe_relative(root, str(relative))
            except ValueError:
                updated = dict(record, state="stale", stale_reason="invalid evidence path")
                upsert_record(root, updated)
                changed.append(record["id"])
                break
            try:
                current = sha256_file(path) if path.is_file() else None
            except OSError:
                current = None
            if current != expected:
                updated = dict(record)
                updated["state"] = "stale"
                updated["stale_reason"] = f"evidence changed or disappeared: {relative}"
                updated["stale_at"] = utc_now()
                upsert_record(root, updated)
                changed.append(record["id"])
                break
    return changed


@locked
def scan_project(root: Path, *, max_files: int = 10000, full: bool = False) -> dict[str, Any]:
    root = root.resolve()
    if max_files < 1:
        raise ValueError("max_files must be positive")
    candidates = collect_files(root, max_files=max_files + 1)
    truncated = len(candidates) > max_files
    files = candidates[:max_files]
    from .incremental import AnalysisCache, config_digest, digest
    analysis = AnalysisCache(root, full=full)
    config = config_digest(root)
    file_snapshot, hash_errors = {}, []
    for path in files:
        relative = path.relative_to(root).as_posix()
        try:
            stat = path.stat()
            hashed = sha256_file(path)
            after = path.stat()
            if (stat.st_size,stat.st_mtime_ns) != (after.st_size,after.st_mtime_ns):
                hash_errors.append(relative); continue
            file_snapshot[relative] = {'sha256':hashed,'size':stat.st_size}
        except OSError: hash_errors.append(relative)
    def providers(directory):
        prefix = directory.relative_to(root).as_posix()
        inputs = {name: info['sha256'] for name,info in file_snapshot.items()
                  if Path(name).parent == directory.relative_to(root) or
                  name.startswith((prefix + '/' if prefix != '.' else '') + 'tests/test')}
        # Include all provider dependencies even when excluded from discovery.
        for name in ('package.json','pyproject.toml','requirements.txt','Cargo.toml','go.mod','pom.xml',
                     'build.gradle','build.gradle.kts','tsconfig.json','uv.lock','poetry.lock',
                     'package-lock.json','pnpm-lock.yaml','yarn.lock','bun.lockb'):
            path = directory/name
            inputs['provider:' + name] = sha256_file(path) if path.is_file() and not path.is_symlink() else None
        fingerprint = digest([inputs,config])
        def parse():
            results = [fn(directory) for fn in (_package_info,_python_info,_other_info)]
            return [[item for result in results for item in result[index]] for index in range(3)]
        return analysis.get('providers:' + prefix, fingerprint, parse)
    snapshot = git_snapshot(root)
    previous = load_records(root)
    stale = _mark_stale_records(root, previous)

    facts: list[str] = []
    commands: list[str] = []
    evidence: list[dict[str, Any]] = []
    provider_facts, provider_commands, provider_evidence = providers(root)
    facts.extend(provider_facts); commands.extend(provider_commands); evidence.extend(provider_evidence)
    nested_roots = sorted({path.parent for path in files if path.parent != root and path.name in {"package.json", "pyproject.toml", "requirements.txt", "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts"}})
    for nested in nested_roots[:48]:
        prefix = nested.relative_to(root).as_posix()
        sub_facts, sub_commands, sub_evidence = providers(nested)
        facts.extend(f"Subproject {prefix}: {fact}" for fact in sub_facts)
        commands.extend(f"(cd {shlex.quote(prefix)} && {command})" for command in sub_commands)
        evidence.extend({**item, "path": f"{prefix}/{item['path']}"} for item in sub_evidence)
    if not facts:
        facts.append("No recognized package manifest; inspect the repository structure manually.")
    facts = list(dict.fromkeys(facts))
    commands = list(dict.fromkeys(commands))
    if (root / "README.md").exists():
        evidence.append(_evidence(root, "README.md"))

    generated: list[dict[str, Any]] = []
    generated.append(make_record(
        record_type="fact",
        record_id="fact.project.identity",
        scope="project",
        statement=f"Project: {root.name}",
        state="verified",
        origin="scanner",
        evidence=[{"kind": "filesystem", "path": "."}],
        stability="stable",
    ))
    generated.append(make_record(
        record_type="fact",
        record_id="fact.project.stack",
        scope="project/stack",
        statement="\n".join(facts),
        state="verified",
        origin="scanner",
        evidence=evidence,
        stability="stable",
    ))
    if commands:
        generated.append(make_record(
            record_type="procedure",
            record_id="procedure.project.commands",
            scope="project/commands",
            statement="Recommended commands discovered from project manifests:\n" + "\n".join(f"- `{item}`" for item in commands),
            state="verified",
            origin="scanner",
            evidence=evidence,
            stability="stable",
        ))
    generated.append(make_record(
        record_type="fact",
        record_id="fact.project.layout",
        scope="project/layout",
        statement="Top-level repository layout:\n" + _top_level_layout(root, files),
        state="verified",
        origin="scanner",
        evidence=[{"kind": "filesystem_snapshot", "file_count": len(files)}],
        stability="volatile",
    ))
    generated.append(make_record(
        record_type="fact",
        record_id="fact.project.git",
        scope="project/git",
        statement=json.dumps({key: snapshot[key] for key in ("is_git", "head", "branch", "remote", "dirty")}, ensure_ascii=False, sort_keys=True),
        state="verified",
        origin="scanner",
        evidence=[{"kind": "git-snapshot", **{key:snapshot[key] for key in ("is_git","head","branch","remote","status_hash")}}],
        stability="volatile",
    ))

    for record in generated:
        upsert_record(root, normalize_record(record))
    generated_ids = {record["id"] for record in generated}
    for record in previous:
        if record.get("origin") == "scanner" and record["id"] not in generated_ids and record.get("state") != "superseded":
            upsert_record(root, dict(record, state="superseded", stale_reason="No longer derived from project manifests"))
    analysis.save()
    write_json_atomic(cache_dir(root) / "snapshot.json", {
        "generated_at": utc_now(),
        "git": snapshot,
        "files": file_snapshot,
        "truncated": truncated,
        "subprojects_truncated": len(nested_roots) > 48,
        "hash_errors": hash_errors,
        "analysis": analysis.stats(),
    })

    return {
        "files": len(files),
        "truncated": truncated,
        "subprojects": [path.relative_to(root).as_posix() for path in nested_roots[:48]],
        "subprojects_truncated": len(nested_roots) > 48,
        "hash_errors": hash_errors,
        "analysis": analysis.stats(),
        "generated_records": [record["id"] for record in generated],
        "stale_records": stale,
        "git": snapshot,
        "commands": commands,
    }
