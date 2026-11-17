"""Command-line interface for PCTX."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sys
from typing import Any

from . import __version__
from .adapters import TARGETS, sync_adapters
from .architecture import refresh_architecture, update_architecture
from .compile import compile_context, export_context, search_records
from .retrieval import read_records
from .continuity import capture_snapshot, compare_snapshot, task_differences
from .review import review_queue, review_record
from .history import record_history, restore_record, payload as record_payload
from .doctor import run_doctor
from .model import make_record
from .mcp import serve as serve_mcp
from .scan import git_snapshot, scan_project
from .storage import (
    context_dir,
    init_context,
    load_handoff,
    load_manifest,
    load_records,
    safe_relative,
    sha256_file,
    upsert_record,
    write_handoff,
    write_text_atomic,
)
from .tasks import checkpoint_task, ensure_tasks_file, finish_task, load_tasks, render_tasks_markdown, start_task


def _json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _record_ttl(value: str) -> int:
    match = re.fullmatch(r'(\d+)([smhdw]?)', value, re.IGNORECASE)
    if match:
        seconds = int(match[1]) * {'':1,'s':1,'m':60,'h':3600,'d':86400,'w':604800}[match[2].lower()]
        if 1 <= seconds <= 31536000:
            return seconds
    raise argparse.ArgumentTypeError('TTL must be 1..31536000 seconds, or an integer with s/m/h/d/w (for example 30m, 24h, 1d)')


def _evidence_from_paths(root: Path, paths: list[str]) -> list[dict[str, Any]]:
    result = []
    for relative in paths:
        if relative.startswith('git:'):
            from .freshness import git_evidence
            result.append(git_evidence(root,relative[4:]));continue
        safe_relative(root, relative)
        path = root / relative
        item: dict[str, Any] = {"kind": "file", "path": relative}
        if path.is_file():
            item["content_hash"] = sha256_file(path)
        result.append(item)
    return result


def _require_context(root: Path) -> None:
    if not (context_dir(root) / "manifest.json").exists():
        raise RuntimeError(f"PCTX is not initialized in {root}; run `pctx --root {root} init` first")


def _cmd_init(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    manifest, created = init_context(root, args.name)
    # These operations are idempotent, so a previously interrupted init can be
    # repaired by running init again.
    ensure_tasks_file(root)
    refresh_architecture(root)
    export_context(root)
    sync_adapters(root, ["agents"])
    result = {"root": str(root), "created": created, "project_id": manifest["project_id"], "export": str(root / "PROJECT_CONTEXT.md"), "architecture": str(root / "architecture.md"), "tasks": str(root / "TASKS.md")}
    _json(result) if args.json else print(f"PCTX {'initialized' if created else 'already initialized'}: {root}\nProject ID: {manifest['project_id']}")
    return 0


def _cmd_scan(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    _require_context(root)
    from .service import refresh_project
    report = refresh_project(root, max_files=args.max_files, full=args.full)
    result = {**report["scan"], "architecture": report["architecture"], "export": report["export"], "export_tokens": report["tokens"], "changes": report["changes"]}
    _json(result) if args.json else _print_scan(result)
    return 0


def _print_scan(result: dict[str, Any]) -> None:
    print(f"Scanned {result['files']} files")
    print(f"Generated: {', '.join(result['generated_records'])}")
    print(f"Export: {result['export']} ({result['export_tokens']} approximate tokens)")
    if result.get("stale_records"):
        print(f"Review required: {len(result['stale_records'])} record(s) became stale")
    if result.get("git", {}).get("dirty"):
        print("Working tree: dirty")


def _cmd_export(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    _require_context(root)
    refresh_architecture(root)
    ensure_tasks_file(root)
    if args.policy:
        from .storage import save_manifest
        manifest = load_manifest(root); manifest['exports'] = {'mode':args.policy}; save_manifest(root, manifest)
    output = safe_relative(root, args.output) if args.output else None
    target, info = export_context(root, output, force=True)
    from .service import sync_installed_adapters
    sync_installed_adapters(root, force=True)
    result = {"output": str(target), **info}
    _json(result) if args.json else print(f"Wrote {target}\nApproximate tokens: {info['approximate_tokens']}\nRecord digest: {info['record_digest']}")
    return 0


def _cmd_context(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    _require_context(root)
    if not args.task:
        raise ValueError("context requires --task")
    if args.budget is not None and not 256 <= args.budget <= 100000:
        raise ValueError("budget must be between 256 and 100000")
    if args.read_only and args.output:
        raise ValueError('Read-only context writes only to stdout; omit --output')
    if not args.read_only:
        start_task(root, args.task, origin="cli")
        from .service import refresh_project
        refresh_project(root)
    budget = args.budget or int(load_manifest(root).get("budgets", {}).get("task_tokens", 8000))
    text, info = compile_context(root, task=args.task, budget=budget)
    if args.output:
        target = safe_relative(root, args.output)
        write_text_atomic(target, text)
        if args.json:
            _json({"output": str(target), **info})
        else:
            print(f"Wrote {target}\nApproximate tokens: {info['approximate_tokens']} / {budget}")
    else:
        if args.json:
            _json({'context': text, **info})
        else:
            print(text, end="")
    if info["approximate_tokens"] > budget:
        print(f"PCTX: compiled context is over the requested approximate budget ({info['approximate_tokens']} > {budget})", file=sys.stderr)
        return 2
    return 0


def _cmd_record(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    _require_context(root)
    evidence = _evidence_from_paths(root, args.evidence or [])
    from .freshness import git_evidence
    evidence += [git_evidence(root, ref) for ref in args.git_evidence]
    record = make_record(
        record_type=args.type,
        statement=args.statement,
        scope=args.scope,
        state=args.state,
        origin=args.origin,
        evidence=evidence,
        record_id=args.id,
        tags=args.tag or [],
        links=[{"relation": x.split(":", 1)[0], "target": x.partition(":")[2]} for x in args.link] + [{'relation':'replaces','target':'record:'+id} for id in args.replaces],
        claim_key=args.claim_key,
        stability=args.stability,
        sensitivity=args.sensitivity,
    )
    import shlex
    existing = next((r for r in load_records(root) if r['id']==record['id']), {})
    for key in ['ttl_seconds','expires_at','roles','check']:
        if key in existing: record[key] = existing[key]
    if args.ttl is not None:
        record['ttl_seconds'] = args.ttl
        if args.expires_at is None: record.pop('expires_at',None)
    if args.expires_at is not None: record['expires_at'] = args.expires_at
    if args.role is not None: record['roles'] = args.role
    if args.check_command is not None: record['check'] = {'argv':shlex.split(args.check_command),'timeout':args.check_timeout}
    saved = upsert_record(root, record)
    if args.export:
        export_context(root)
    if not args.quiet:
        _json(record_payload(saved)) if args.json else print(f"Saved record {saved['id']} ({saved['state']})")
    return 0


def _cmd_decision(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    _require_context(root)
    statement = args.statement.strip()
    if args.rationale:
        statement += f"\n\nRationale:\n{args.rationale.strip()}"
    if args.rejected:
        statement += "\n\nRejected alternatives:\n" + "\n".join(f"- {item}" for item in args.rejected)
    record = make_record(
        record_type="decision",
        record_id=args.id,
        statement=statement,
        scope=args.scope,
        state="user_asserted",
        origin="user",
        evidence=_evidence_from_paths(root, args.evidence or []),
        stability="stable",
        tags=args.tag or [],
        links=[{"relation": x.split(":", 1)[0], "target": x.partition(":")[2]} for x in args.link] + [{'relation':'replaces','target':'record:'+id} for id in args.replaces],
        claim_key=args.claim_key,
    )
    saved = upsert_record(root, record)
    export_context(root)
    _json(record_payload(saved)) if args.json else print(f"Saved decision {saved['id']}")
    return 0


def _handoff_markdown(handoff: dict[str, Any]) -> str:
    lines = ["# Handoff", "", f"Updated: {handoff.get('updated_at', '')}", "", "## Objective", "", handoff.get("objective", "")]
    if handoff.get("acceptance"):
        lines.extend(["", "## Acceptance", "", *[f"- {item}" for item in handoff["acceptance"]]])
    if handoff.get("next_actions"):
        lines.extend(["", "## Next actions", "", *[f"- {item}" for item in handoff["next_actions"]]])
    if handoff.get("blockers"):
        lines.extend(["", "## Blockers", "", *[f"- {item}" for item in handoff["blockers"]]])
    snapshot = handoff.get("snapshot", {})
    lines.extend(["", "## Resume snapshot", "", f"- Branch: `{snapshot.get('branch')}`", f"- HEAD: `{snapshot.get('head')}`", f"- Working tree: `{'dirty' if snapshot.get('dirty') else 'clean'}`", f"- Status hash: `{snapshot.get('status_hash')}`"])
    return "\n".join(lines) + "\n"


def _cmd_handoff(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    _require_context(root)
    if args.handoff_command == "save":
        from .mcp import _save_handoff
        active = load_tasks(root).get('active') or {}
        handoff = _save_handoff(root, {'objective': args.objective,
            'acceptance': args.acceptance if args.acceptance is not None else active.get('acceptance', []),
            'next_actions': args.next_action if args.next_action is not None else active.get('next_actions', []),
            'blockers': args.blocker if args.blocker is not None else active.get('blockers', [])})
        checkpoint_task(root, title=args.objective, acceptance=handoff['acceptance'],
            next_actions=handoff['next_actions'], blockers=handoff['blockers'])
        export_context(root)
        _json(handoff) if args.json else print('Handoff saved and PROJECT_CONTEXT.md regenerated.')
        return 0

    handoff = load_handoff(root)
    if not handoff:
        raise RuntimeError("No handoff saved yet")
    result = compare_snapshot(root, handoff.get('workspace_snapshot'))
    differences = result['differences']
    if args.handoff_command == "resume":
        text, info = compile_context(root, task=handoff.get("objective", "resume project"), budget=args.budget or 8000)
        result["context"] = text
        result["context_info"] = info
    if args.json:
        _json(result)
    else:
        if differences:
            print('Handoff differs from the current workspace:')
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print('Handoff content snapshot matches the current workspace.')
        if args.handoff_command == "resume":
            print("\n" + result["context"], end="")
    return 0 if not differences else 2


def _cmd_task(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    _require_context(root)
    if args.task_command == "start":
        task = start_task(root, args.title, acceptance=args.acceptance, next_actions=args.next_action, blockers=args.blocker, changed_files=args.changed_file, origin="cli")
    elif args.task_command == "update":
        task = checkpoint_task(root, title=args.title, status=args.status, acceptance=args.acceptance, next_actions=args.next_action, blockers=args.blocker, changed_files=args.changed_file)
        if task is None:
            raise RuntimeError("No active task; use `pctx task start --title ...` first")
    elif args.task_command == "finish":
        task = finish_task(root, title=args.title, acceptance=args.acceptance, next_actions=args.next_action, blockers=args.blocker, changed_files=args.changed_file)
    elif args.task_command == "resume":
        from .tasks import resume_task
        task = resume_task(root, args.id)
    else:
        data = load_tasks(root)
        if args.json:
            _json(data)
        else:
            print(render_tasks_markdown(root, data), end="")
        return 0
    if args.json:
        _json(task)
    else:
        print(f"Task {task['status']}: {task['title']}")
    export_context(root)
    return 0


def _cmd_architecture(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    _require_context(root)
    if args.architecture_command == "refresh":
        result = refresh_architecture(root)
    else:
        nodes = []
        edges = []
        if args.node_id:
            nodes.append({"id": args.node_id, "label": args.label or args.node_id, "kind": args.kind})
        if args.source or args.target:
            if not args.source or not args.target:
                raise ValueError("architecture update requires both --source and --target")
            edges.append({"source": args.source, "target": args.target, "label": args.edge_label or "connects"})
        result = update_architecture(root, nodes=nodes, edges=edges, notes=args.note)
    _json(result) if args.json else print(f"Architecture updated: {result['file']} ({result['nodes']} nodes, {result['edges']} edges)")
    export_context(root)
    return 0


def _cmd_adapters(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    _require_context(root)
    names = [item.strip() for item in args.targets.split(",")] if args.targets else None
    result = sync_adapters(root, names, check=args.check)
    _json(result) if args.json else _print_adapters(result)
    return 1 if args.check and result["drift"] else 0


def _print_adapters(result: dict[str, Any]) -> None:
    for item in result["results"]:
        status = "drift" if result["check"] and item["changed"] else "updated" if item.get("written") else "up to date"
        print(f"{status}: {item['adapter']} -> {item['file']}")


def _cmd_doctor(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    _require_context(root)
    result = run_doctor(root)
    if args.json:
        _json(result)
    else:
        print(f"PCTX doctor: {'OK' if result['ok'] else 'FAILED'}")
        print(f"Records: {result['records']} | errors: {result['errors']} | warnings: {result['warnings']}")
        for finding in result["findings"]:
            suffix = f" [{finding['path']}]" if finding.get("path") else ""
            print(f"{finding['level'].upper()} {finding['code']}: {finding['message']}{suffix}")
    return 0 if result["ok"] else 1


def _cmd_search(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    _require_context(root)
    result = search_records(root, args.query)
    if args.json:
        _json(result)
    else:
        for record in result:
            print(f"{record['id']} [{record['state']}] {record['statement'].splitlines()[0]}")
    return 0


def _cmd_mcp(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    _require_context(root)
    from .service import ProjectWatcher
    if args.watch and not args.allow_write:
        raise ValueError("MCP --watch requires --allow-write")
    watcher = ProjectWatcher(root) if args.watch else None
    if watcher:
        watcher.start()
    try:
        return serve_mcp(root, allow_write=args.allow_write)
    finally:
        if watcher:
            watcher.stop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pctx", description="Portable, evidence-backed project context compiler")
    parser.add_argument("--version", action="version", version=f"pctx {__version__}")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="project root (default: current directory)")
    sub = parser.add_subparsers(dest="command", required=True)

    index = sub.add_parser('index', help='rebuild the disposable local search index')
    index.add_argument('--model', help='explicit offline ONNX embedding bundle directory')
    for command in ('lookup', 'expand', 'neighbors'):
        tool = sub.add_parser(command, help='bounded public knowledge retrieval')
        tool.add_argument('query' if command == 'lookup' else 'reference')
        tool.add_argument('--budget', type=int, default=2000)
        if command in ('lookup', 'neighbors'):
            tool.add_argument('--limit', type=int, default=6 if command == 'lookup' else 20)
        if command == 'lookup':
            tool.add_argument('--kind', choices=['all', 'record', 'document'], default='all')
            tool.add_argument('--mode', choices=['lexical', 'hybrid'], default='lexical')
            tool.add_argument('--model')
            tool.add_argument('--offset', type=int, default=0)
        if command == 'neighbors':
            tool.add_argument('--depth', type=int, default=1)

    init = sub.add_parser("init", help="initialize .project-context")
    init.add_argument("--name")
    init.add_argument("--json", action="store_true")

    scan = sub.add_parser("scan", help="statically inspect the project and update verified records")
    scan.add_argument("--max-files", type=int, default=10000)
    scan.add_argument("--json", action="store_true")
    scan.add_argument("--full", action="store_true", help="bypass parser caches and verify all content")

    export = sub.add_parser("export", help="generate the complete PROJECT_CONTEXT.md")
    export.add_argument("--output")
    export.add_argument("--json", action="store_true")

    context = sub.add_parser("context", help="compile a task-focused context pack")
    context.add_argument("--task", required=True)
    context.add_argument("--budget", type=int)
    context.add_argument("--output")
    context.add_argument("--json", action="store_true")
    context.add_argument("--read-only", action="store_true", help="compile without scanning, updating tasks or writing views")

    record = sub.add_parser("record", help="add or replace a typed record")
    record.add_argument("--type", choices=["fact", "constraint", "procedure", "issue", "attempt", "next_action", "unknown", "note"], default="note")
    record.add_argument("--statement", required=True)
    record.add_argument("--scope", default="project")
    record.add_argument("--state", choices=["verified", "user_asserted", "inferred", "unknown"], default="user_asserted")
    record.add_argument("--origin", default="user")
    record.add_argument("--id")
    record.add_argument("--evidence", action="append")
    record.add_argument("--tag", action="append")
    record.add_argument("--stability", default="stable")
    record.add_argument("--sensitivity", choices=["public", "internal", "private", "secret"], default="internal")
    record.add_argument("--export", action="store_true")
    record.add_argument("--json", action="store_true")
    record.add_argument('--quiet', action='store_true')
    record.add_argument('--replaces', action='append', default=[], help='existing visible OLD_ID in this root; update the same --id without --replaces')
    record.add_argument('--ttl', type=_record_ttl, help='validity in seconds or integer s/m/h/d/w, e.g. 86400 or 1d')
    record.add_argument('--expires-at')
    record.add_argument('--role', action='append')
    record.add_argument('--git-evidence', action='append', default=[])
    record.add_argument('--check-command')
    record.add_argument('--check-timeout', type=int, default=60)
    record.add_argument("--claim-key")
    record.add_argument("--link", action="append", default=[], help="relation:record:ID or relation:file:path")

    decision = sub.add_parser("decision", help="record an explicit project decision")
    decision.add_argument("--statement", required=True)
    decision.add_argument("--rationale")
    decision.add_argument("--rejected", action="append")
    decision.add_argument("--scope", default="project")
    decision.add_argument("--id")
    decision.add_argument("--evidence", action="append")
    decision.add_argument("--tag", action="append")
    decision.add_argument("--json", action="store_true")
    decision.add_argument("--claim-key")
    decision.add_argument('--replaces',action='append',default=[])
    decision.add_argument("--link", action="append", default=[], help="relation:record:ID or relation:file:path")

    handoff = sub.add_parser("handoff", help="save or verify a session handoff")
    handoff_sub = handoff.add_subparsers(dest="handoff_command", required=True)
    save = handoff_sub.add_parser("save")
    save.add_argument("--objective", required=True)
    save.add_argument("--acceptance", action="append")
    save.add_argument("--next-action", action="append")
    save.add_argument("--blocker", action="append")
    save.add_argument("--json", action="store_true")
    for name in ("verify", "resume"):
        item = handoff_sub.add_parser(name)
        item.add_argument("--budget", type=int)
        item.add_argument("--json", action="store_true")

    task = sub.add_parser("task", help="start, checkpoint or finish resumable work")
    task_sub = task.add_subparsers(dest="task_command", required=True)
    task_start = task_sub.add_parser("start")
    task_start.add_argument("--title", required=True)
    task_update = task_sub.add_parser("update")
    task_update.add_argument("--title")
    task_update.add_argument("--status", choices=["active", "paused", "blocked"], default="active")
    task_finish = task_sub.add_parser("finish")
    task_finish.add_argument("--title", required=True)
    for item in (task_start, task_update, task_finish):
        item.add_argument("--acceptance", action="append")
        item.add_argument("--next-action", action="append")
        item.add_argument("--blocker", action="append")
        item.add_argument("--changed-file", action="append")
        item.add_argument("--json", action="store_true")
    task_list = task_sub.add_parser("list")
    task_list.add_argument("--json", action="store_true")
    task_resume = task_sub.add_parser("resume")
    task_resume.add_argument("--id")
    task_resume.add_argument("--json", action="store_true")

    architecture = sub.add_parser("architecture", help="refresh or extend the Mermaid architecture map")
    architecture_sub = architecture.add_subparsers(dest="architecture_command", required=True)
    architecture_sub.add_parser("refresh")
    architecture_update = architecture_sub.add_parser("update")
    architecture_update.add_argument("--node-id")
    architecture_update.add_argument("--label")
    architecture_update.add_argument("--kind", default="custom")
    architecture_update.add_argument("--source")
    architecture_update.add_argument("--target")
    architecture_update.add_argument("--edge-label")
    architecture_update.add_argument("--note", action="append")
    for item in (architecture_sub.choices["refresh"], architecture_update):
        item.add_argument("--json", action="store_true")

    adapters = sub.add_parser("adapters", help="synchronize AI-tool bootstrap files")
    adapters_sub = adapters.add_subparsers(dest="adapters_command", required=True)
    sync = adapters_sub.add_parser("sync")
    sync.add_argument("--targets", help=f"comma-separated names: {', '.join(TARGETS)}")
    sync.add_argument("--check", action="store_true")
    sync.add_argument("--json", action="store_true")

    doctor = sub.add_parser("doctor", help="run read-only health and security checks")
    doctor.add_argument("--json", action="store_true")

    search = sub.add_parser("search", help="search canonical records")
    search.add_argument("query")
    search.add_argument("--json", action="store_true")

    read = sub.add_parser('read', help='expand a public record or component without writing')
    choice = read.add_mutually_exclusive_group(required=True)
    choice.add_argument('--id')
    choice.add_argument('--component')
    read.add_argument('--limit', type=int, default=20)

    differences = sub.add_parser('differences', help='read content changes since a task checkpoint')
    differences.add_argument('--id')

    history = sub.add_parser('history', help='inspect, compare or restore canonical record revisions')
    history.add_argument('--id', required=True)
    history.add_argument('--revision', type=int)
    history.add_argument('--compare', type=int)
    history.add_argument('--restore', type=int, help='create a new inferred revision from this revision')
    history.add_argument('--expected-revision', type=int, help='required current revision guard for restore')

    review = sub.add_parser('review', help='inspect evidence and explicitly review public knowledge')
    review.add_argument('--offset', type=int, default=0)
    review.add_argument('--limit', type=int, default=50)
    review.add_argument('--id')
    review.add_argument('--action', choices=['confirm', 'correct', 'supersede'])
    review.add_argument('--expected-revision', type=int)
    review.add_argument('--statement')
    review.add_argument('--replacement-id')

    diagnose = sub.add_parser('diagnose', help='finite local MCP handshake and permission diagnostic')
    diagnose.add_argument('--write-mode', action='store_true')
    diagnose.add_argument('--timeout', type=float, default=10)

    backup = sub.add_parser('backup', help='private local backups, guarded restore and recovery')
    backup_sub = backup.add_subparsers(dest='backup_command', required=True)
    create = backup_sub.add_parser('create'); create.add_argument('--output', type=Path)
    restore = backup_sub.add_parser('restore'); restore.add_argument('archive', type=Path)
    restore.add_argument('--apply', action='store_true'); restore.add_argument('--expected-state')
    backup_sub.add_parser('recover')
    migrate = sub.add_parser('migrate', help='preview or apply optional history initialization for schema 1')
    migrate.add_argument('--apply', action='store_true'); migrate.add_argument('--expected-state')

    mcp = sub.add_parser("mcp", help="serve local MCP over stdin/stdout")
    mcp_sub = mcp.add_subparsers(dest="mcp_command", required=True)
    serve = mcp_sub.add_parser("serve")
    serve.add_argument("--allow-write", action="store_true", help="enable explicit pctx_record writes")
    serve.add_argument("--watch", action="store_true", help="automatically refresh changed source files while the write-enabled MCP runs")

    gui = sub.add_parser("gui", help="open the local project dashboard")
    gui.add_argument("--port", type=int, default=0, help="loopback port; 0 chooses a free port")
    gui.add_argument("--no-browser", action="store_true")
    watch = sub.add_parser("watch", help="refresh derived memory when source files change")
    watch.add_argument("--interval", type=float, default=5)
    watch.add_argument("--once", action="store_true")
    integrate = sub.add_parser("integrate", help="preview or install an MCP client configuration")
    integrate.add_argument("--client", choices=["generic", "vscode", "cursor", "claude-code"], default="generic")
    integrate.add_argument("--write", action="store_true", help="merge configuration into the selected client file")
    integrate.add_argument("--read-only", action="store_true")
    sub.add_parser("guide", help="print a prompt for an AI connected through a Master MCP terminal")
    sub.add_parser("install-desktop", help="add PCTX to the Linux application menu")
    sub.add_parser("portable", help="bundle PCTX inside the selected project for sandboxed terminal tools")
    call = sub.add_parser("call", help="invoke a PCTX tool once through a terminal bridge")
    call.add_argument("tool")
    call.add_argument("--args", default="{}", help="JSON tool arguments")
    call.add_argument("--allow-write", action="store_true")

    from .planning_model import KINDS, STATUSES, DIFFICULTIES, RISKS, PRIORITIES, OUTCOMES
    plan = sub.add_parser('plan', help='Goals, checklists, difficulty and recorded reviews')
    plan.add_argument('action', choices=['summary', 'list', 'detail', 'history', 'create', 'edit', 'status', 'review'])
    for key in ['id', 'title', 'description', 'parent', 'goal', 'owner', 'reason', 'difficulty_reason', 'summary', 'reviewer', 'event_id']:
        plan.add_argument('--' + key.replace('_', '-'))
    for key, values in [('kind', KINDS), ('status', STATUSES), ('difficulty', DIFFICULTIES), ('risk', RISKS), ('priority', PRIORITIES), ('outcome', OUTCOMES)]:
        plan.add_argument('--' + key, choices=values)
    for key in ['dependencies', 'criteria', 'evidence', 'covered_criteria']:
        plan.add_argument('--' + key.replace('_', '-'), action='append')
    plan.add_argument('--expected-revision', type=int)
    plan.add_argument('--ready', action='store_true', default=None)
    plan.add_argument('--offset', type=int, default=0)
    plan.add_argument('--limit', type=int, default=20)
    plan.add_argument('--budget', type=int, default=2000)
    coordinate = sub.add_parser('coordinate', help='Reserve shared tasks and file areas for cooperating AI sessions')
    coordinate.add_argument('action', choices=['list', 'detail', 'history', 'claim', 'renew', 'release', 'cleanup'])
    for key in ['id', 'session_id', 'task_id', 'summary']:
        coordinate.add_argument('--' + key.replace('_', '-'))
    coordinate.add_argument('--path', dest='paths', action='append')
    coordinate.add_argument('--status', choices=['active', 'expired', 'released', 'clock_anomaly'])
    coordinate.add_argument('--ttl', type=int)
    coordinate.add_argument('--expected-revision', type=int)
    coordinate.add_argument('--offset', type=int, default=0)
    coordinate.add_argument('--limit', type=int, default=20)
    coordinate.add_argument('--budget', type=int, default=2000)
    plan.add_argument('--session-id')
    plan.add_argument('--lease-id')
    export.add_argument('--policy', choices=['auto','manual'])
    compact = sub.add_parser('brief', help='Small fixed prompt for a coordinator or worker')
    compact.add_argument('--budget',type=int,default=800); compact.add_argument('--role'); compact.add_argument('--json',action='store_true')
    verify = sub.add_parser('verify', help='Preview or explicitly run a record check command')
    verify.add_argument('--id',required=True); verify.add_argument('--run',action='store_true'); verify.add_argument('--expected-revision',type=int); verify.add_argument('--quiet',action='store_true')
    reports = sub.add_parser('import-reports',help='Import worker report sections without duplicates')
    reports.add_argument('--path',dest='paths',action='append'); reports.add_argument('--glob',dest='patterns',action='append'); reports.add_argument('--role'); reports.add_argument('--quiet',action='store_true')
    report = sub.add_parser('report',help='Write/import report documents without a code reservation')
    report.add_argument('--path',required=True); report.add_argument('--text',required=True); report.add_argument('--append',action='store_true'); report.add_argument('--expected-hash'); report.add_argument('--role'); report.add_argument('--quiet',action='store_true')
    call.add_argument('--quiet',action='store_true')
    return parser


def _dispatch(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command in {'brief','verify','import-reports','report'}:
            root = args.root.resolve(); _require_context(root)
            if args.command == 'brief':
                from .briefing import brief
                result = brief(root,budget=args.budget,role=args.role)
                _json(result) if args.json else print(result['text'],end='')
                return 0
            if args.command == 'verify':
                from .verification import verify
                result = verify(root,args.id,execute=args.run,expected_revision=args.expected_revision)
            elif args.command == 'import-reports':
                from .worker_reports import import_reports
                result = import_reports(root,paths=args.paths,patterns=args.patterns,role=args.role)
            else:
                from .worker_reports import write_report
                result = write_report(root,path=args.path,text=args.text,append=args.append,expected_hash=args.expected_hash,role=args.role)
            if not args.quiet: _json(result)
            return 1 if args.command=='verify' and args.run and result['state']!='verified' else 0
        if args.command == 'coordinate':
            from .coordination import query, update
            from .knowledge import wire
            _require_context(args.root)
            reads = args.action in {'list', 'detail', 'history'}
            keys = ['id', 'session_id', 'status', 'offset', 'limit', 'budget'] if reads else ['id', 'session_id', 'task_id', 'paths', 'ttl', 'expected_revision', 'summary']
            options = {k: getattr(args, k) for k in keys if getattr(args, k) is not None}
            if not reads and args.action != 'cleanup' and 'session_id' not in options:
                raise ValueError('Writes require --session-id')
            print(wire((query if reads else update)(args.root.resolve(), args.action, **options)))
            return 0
        if args.command == 'plan':
            from .planning import query, update
            from .knowledge import wire
            _require_context(args.root)
            reads = args.action in {'summary', 'list', 'detail', 'history'}
            keys = ['id', 'parent', 'goal', 'status', 'kind', 'difficulty', 'risk', 'ready', 'offset', 'limit', 'budget'] if reads else ['id', 'expected_revision', 'title', 'kind', 'description', 'parent', 'dependencies', 'priority', 'owner', 'criteria', 'difficulty', 'difficulty_reason', 'risk', 'status', 'reason', 'outcome', 'summary', 'reviewer', 'evidence', 'covered_criteria', 'event_id', 'session_id', 'lease_id']
            options = {k: getattr(args, k) for k in keys if getattr(args, k) is not None}
            print(wire((query if reads else update)(args.root.resolve(), args.action, **options)))
            return 0
        if args.command == "gui":
            from .dashboard import serve_dashboard
            return serve_dashboard(args.root, port=args.port, open_browser=not args.no_browser)
        if args.command == "guide":
            from .integrations import bridge_prompt
            print(bridge_prompt(args.root))
            return 0
        if args.command == "install-desktop":
            from .integrations import install_desktop
            print(install_desktop())
            return 0
        if args.command == "portable":
            from .portable import build_portable
            _require_context(args.root)
            _json(build_portable(args.root.resolve()))
            return 0
        if args.command == "integrate":
            from .integrations import configuration, install_configuration
            operation = install_configuration if args.write else configuration
            _json(operation(args.root.resolve(), args.client, allow_write=not args.read_only))
            return 0
        if args.command == "call":
            from .mcp import handle_request
            _require_context(args.root)
            response = handle_request(args.root.resolve(), {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": args.tool, "arguments": json.loads(args.args)}}, allow_write=args.allow_write)
            if not args.quiet: _json(response)
            elif response.get('error') or response.get('result',{}).get('isError'): print('PCTX call failed; repeat without --quiet for details',file=sys.stderr)
            return 1 if response.get("error") or response.get("result", {}).get("isError") else 0
        if args.command == "watch":
            from .service import ProjectWatcher, refresh_project
            _require_context(args.root)
            watcher = ProjectWatcher(args.root, args.interval)
            if args.once:
                _json(refresh_project(args.root))
                return 0
            watcher.start()
            print(f"Watching {args.root.resolve()}; Ctrl+C stops. Only derived facts are updated.", flush=True)
            try:
                while not watcher.stop_event.wait(1):
                    if watcher.error:
                        print(watcher.error, file=sys.stderr)
                        watcher.error = None
            except KeyboardInterrupt:
                watcher.stop()
            return 0
        if args.command == "init":
            return _cmd_init(args)
        if args.command == "scan":
            return _cmd_scan(args)
        if args.command == "export":
            return _cmd_export(args)
        if args.command == "context":
            return _cmd_context(args)
        if args.command == "record":
            return _cmd_record(args)
        if args.command == "decision":
            return _cmd_decision(args)
        if args.command == "handoff":
            return _cmd_handoff(args)
        if args.command == "task":
            return _cmd_task(args)
        if args.command == "architecture":
            return _cmd_architecture(args)
        if args.command == "adapters" and args.adapters_command == "sync":
            return _cmd_adapters(args)
        if args.command == "doctor":
            return _cmd_doctor(args)
        if args.command == "search":
            return _cmd_search(args)
        if args.command == 'read':
            _require_context(args.root)
            _json(read_records(args.root.resolve(), record_id=args.id, component=args.component, limit=args.limit))
            return 0
        if args.command == 'diagnose':
            from .diagnostics import diagnose
            result = diagnose(args.root,allow_write=args.write_mode,timeout=args.timeout)
            _json(result);return 0 if result['ok'] else 1
        if args.command in {'backup', 'migrate'}:
            from .backup import create_backup, preview_restore, restore_backup, recover_restore, migrate_history
            root = args.root.resolve()
            if args.command == 'migrate':
                if args.apply and not args.expected_state: raise ValueError('Apply requires --expected-state from preview')
                result = migrate_history(root, expected_state=args.expected_state if args.apply else None)
                mutated = args.apply
            elif args.backup_command == 'create':
                result = create_backup(root, args.output); mutated = False
            elif args.backup_command == 'recover':
                result = recover_restore(root); mutated = True
            else:
                if args.apply and not args.expected_state: raise ValueError('Apply requires --expected-state from preview')
                result = restore_backup(root,args.archive,args.expected_state) if args.apply else preview_restore(root,args.archive)
                mutated = args.apply
            if mutated:
                from .service import refresh_project
                refresh_project(root)
            _json(result);return 0
        if args.command == 'differences':
            _require_context(args.root)
            _json(task_differences(args.root.resolve(), args.id))
            return 0
        if args.command == 'review':
            _require_context(args.root)
            if args.action:
                if not args.id or args.expected_revision is None:
                    raise ValueError('Review requires --id and --expected-revision')
                _json(review_record(args.root.resolve(), args.id, args.action,
                    expected_revision=args.expected_revision, statement=args.statement,
                    replacement_id=args.replacement_id, actor='user'))
                export_context(args.root.resolve())
            else:
                _json(review_queue(args.root.resolve(), offset=args.offset, limit=args.limit))
            return 0
        if args.command == 'history':
            _require_context(args.root)
            if args.restore is not None:
                if args.expected_revision is None or args.revision is not None or args.compare is not None:
                    raise ValueError('Restore requires --expected-revision and cannot be combined with inspection')
                _json(restore_record(args.root.resolve(), args.id, args.restore, args.expected_revision))
                export_context(args.root.resolve())
                from .service import sync_installed_adapters
                sync_installed_adapters(args.root.resolve())
            else:
                _json(record_history(args.root.resolve(), args.id, args.revision, args.compare))
            return 0
        if args.command in {'index', 'lookup', 'expand', 'neighbors'}:
            from .knowledge import build_index, lookup, expand, neighbors, wire
            root = args.root.resolve()
            if args.command == 'index':
                result = build_index(root, model=args.model)
            elif args.command == 'lookup':
                result = lookup(root, args.query, limit=args.limit, budget=args.budget,
                    kind=args.kind, mode=args.mode, model=args.model, offset=args.offset)
            elif args.command == 'expand':
                result = expand(root, args.reference, budget=args.budget)
            else:
                result = neighbors(root, args.reference, depth=args.depth, limit=args.limit, budget=args.budget)
            print(wire(result))
            return 0
        if args.command == "mcp" and args.mcp_command == "serve":
            return _cmd_mcp(args)
        parser.error("unknown command")
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"pctx: error: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    from .service import sync_installed_adapters, validate_workspace
    from .storage import project_lock
    args = build_parser().parse_args(argv)
    persistent = args.command in {"init", "index", "scan", "export", "context", "record", "decision", "handoff", "task", "architecture", "adapters"}
    if args.command in {'report','import-reports'}:
        persistent = True
    if args.command == 'coordinate' and args.action in {'claim', 'renew', 'release', 'cleanup'}:
        persistent = True
    if args.command == 'plan' and args.action in {'create', 'edit', 'status', 'review'}:
        persistent = True
    if args.command == "handoff" and args.handoff_command in {"verify", "resume"}:
        persistent = False
    if args.command == 'context' and args.read_only:
        persistent = False
    if args.command == 'review' and args.action:
        persistent = True
    if args.command == 'history' and args.restore is not None:
        persistent = True
    try:
        if persistent:
            if args.command == "init":
                args.root.mkdir(parents=True, exist_ok=True)
            root = validate_workspace(args.root)
            with project_lock(root):
                result = _dispatch(argv)
                if result == 0 and args.command != "adapters":
                    sync_installed_adapters(root)
                return result
        if args.command in {'brief', 'coordinate', 'plan', 'lookup', 'expand', 'neighbors', 'read', 'search', 'history', 'review', 'differences', 'doctor', 'handoff', 'context'} and (args.root / '.project-context/.lock').exists():
            with project_lock(args.root.resolve()):
                return _dispatch(argv)
        return _dispatch(argv)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"pctx: error: {exc}", file=sys.stderr)
        return 1
