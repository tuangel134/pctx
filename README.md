<div align="center">
  <img src="pctx/web/icon.svg" width="76" alt="PCTX logo">
  <h1>PCTX</h1>
  <p><strong>Portable, evidence-backed project memory for AI coding assistants.</strong></p>
  <p>
    <a href="README.es.md">Español</a> ·
    <a href="#quick-start">Quick start</a> ·
    <a href="#mcp-setup">MCP</a> ·
    <a href="docs/README.md">Docs</a>
  </p>
  <p>
    <a href="https://github.com/tuangel134/pctx/actions/workflows/ci.yml"><img src="https://github.com/tuangel134/pctx/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
    <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python 3.10+"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT"></a>
    <a href="docs/INTEGRACIONES.md"><img src="https://img.shields.io/badge/MCP-stdio-6f42c1.svg" alt="MCP"></a>
    <img src="https://img.shields.io/badge/status-beta-orange.svg" alt="Beta">
  </p>
</div>

PCTX compiles the durable knowledge of a project — facts, decisions,
constraints, procedures, confirmed failures and handoffs — into a small,
portable context file and task-scoped packs. Any assistant can pick up the work
without re-reading the whole repository or replaying a chat transcript.

It is local-first, has **zero runtime dependencies**, and records *why* a claim
is believed: state, origin, evidence, freshness and sensitivity.

![PCTX dashboard](docs/assets/overview.png)

## Why another context tool?

Most "memory" for coding agents is either a giant Markdown file that goes stale,
or a chat log that cannot be audited. PCTX keeps a small, typed record store and
compiles what is relevant:

- **Evidence, not vibes.** Every record carries a state (`verified`,
  `user_asserted`, `inferred`, `stale`, `superseded`), origin and evidence.
  Volatile facts expire; replacements keep history.
- **Fits any assistant.** Plain Markdown and JSON, a stdio MCP server, and
  adapters for `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, Copilot, Cursor and
  Windsurf.
- **Built for several agents at once.** Goals and checklists with difficulty and
  risk, cooperative task/file reservations with TTL, checkpoints and handoffs.
- **Local and boring on purpose.** No accounts, no network calls, no telemetry,
  no embeddings required, and secret-like content is refused before it is stored.

## Quick start

Requires Python 3.10+ and SQLite with FTS5 (standard in CPython builds).

```bash
# Install from this repository (pipx keeps it isolated)
pipx install git+https://github.com/tuangel134/pctx.git

# Inside the project you want to give memory to
cd ~/projects/my-app
pctx init
pctx scan
pctx export
pctx doctor
```

You now have:

| Path | Purpose |
| --- | --- |
| `PROJECT_CONTEXT.md` | Portable, human/LLM-readable context export |
| `architecture.md` | Compact Mermaid map of components and imports |
| `TASKS.md` | Crash-recovery marker for the active task |
| `.project-context/` | Canonical JSON records and machine-local state |

Ask for only what a task needs, within a token budget:

```bash
pctx context --task "add password reset without breaking the API" --budget 8000
pctx brief --budget 800 --role W4
```

Record something durable:

```bash
pctx decision \
  --id decision.storage \
  --statement "Sessions are stored in PostgreSQL" \
  --rationale "The existing migrations and tests already depend on it"

pctx record --type constraint --id constraint.no-secrets \
  --statement "Never store secrets or .env values in project memory" \
  --state user_asserted --export
```

## How it works

```text
project files ──► static scan ──► typed records ──► compiled context
                                      │                  │
                          decisions, evidence,      PROJECT_CONTEXT.md
                          TTL, replacements,        task packs, briefs
                          checklists, leases        MCP tools/resources
```

1. **Scan** inspects manifests, Git state, structure and hashes. It never
   executes project code.
2. **Records** are small JSON documents with stable IDs. Newer states replace
   older ones without deleting history; `--ttl` expires volatile claims.
3. **Compile** produces a portable export, a role brief, or a task-scoped pack
   that fits a token budget.
4. **Verify** can run an explicitly recorded check command and store the
   observed outcome — never automatically, and only on request.

![Task context and worker brief](docs/assets/context.png)

### Record states

| State | Meaning |
| --- | --- |
| `verified` | Backed by current evidence (file hash, Git revision, check result) |
| `user_asserted` | Declared by a person or an explicit decision |
| `inferred` | Written by an AI or imported from a worker report; needs review |
| `stale` | Evidence changed or expired; must be reviewed before trusting it |
| `superseded` | Replaced by a newer record; kept for history |
| `unknown` | Not enough information |

## MCP setup

PCTX speaks MCP over stdio. Generate a client configuration:

```bash
pctx --root /path/to/project integrate --client vscode --write
pctx --root /path/to/project integrate --client cursor --write
pctx --root /path/to/project integrate --client claude-code --write
```

Or add it manually:

```json
{
  "mcpServers": {
    "pctx": {
      "command": "pctx",
      "args": ["--root", "/path/to/project", "mcp", "serve", "--allow-write"]
    }
  }
}
```

- Default `mcp serve` is read-only. Add `--allow-write` so the agent can record
  decisions, checkpoints and handoffs; add `--watch` to refresh derived memory
  while the client keeps the server open.
- The server exposes context, search, plan, coordination and history tools plus
  context/architecture/task resources.
- Client behavior is not guaranteed: `pctx diagnose` checks the protocol
  handshake, not whether a model chooses to use it.

## Working with multiple agents

PCTX does not call or hire models. It gives cooperating sessions a shared,
auditable protocol:

```bash
# Create a goal and tasks with explicit difficulty and risk
pctx plan create --id plan.login --kind goal --title "Ship login" \
  --difficulty intermediate --difficulty-reason "Touches API, UI and sessions" --risk high
pctx plan create --id plan.login-api --parent plan.login --kind task \
  --title "Implement login endpoint" --difficulty medium \
  --difficulty-reason "One route plus tests" --risk medium

# Reserve the task and the exact paths before editing
pctx coordinate claim --session-id ia-login-01 --task-id plan.login-api \
  --path src/auth --path tests/auth --ttl 900

pctx coordinate list --status active --budget 1500
pctx coordinate renew --id <lease-id> --ttl 900
pctx coordinate release --id <lease-id> --summary "Endpoint done; tests pending"
```

Reservations are **cooperative leases**, not OS file locks: editors stay usable,
but every session must respect the protocol. Expired leases stop occupying the
area; a late worker cannot silently overwrite its successor.

![Goals and checklists](docs/assets/plan.png)

## Retrieval

Search is local SQLite FTS5 over records and documents, with budgets and
expandable evidence:

```bash
pctx lookup "authentication flow" --budget 2000
pctx expand <record-or-fragment-id> --budget 1200
pctx neighbors <record-id> --budget 1000
```

Semantic search is optional and fully local: PCTX never downloads models or
calls an API. Install the extra and point it at an ONNX embedding bundle:

```bash
pipx inject pctx numpy onnxruntime tokenizers   # or: pip install -e ".[semantic]"
pctx index --model /path/to/onnx-bundle
pctx lookup "how does login work?" --mode hybrid --model /path/to/onnx-bundle
```

JSON records remain the source of truth; indexes are disposable and queries are
never persisted.

## Installation

```bash
# Isolated install from Git
pipx install git+https://github.com/tuangel134/pctx.git

# Or as a library/editable checkout
git clone https://github.com/tuangel134/pctx.git
cd pctx
python3 -m pip install -e ".[dev]"
```

Linux desktop entry (application menu + `~/.local/bin/pctx`):

```bash
python3 install.py
```

Other platforms work through `pip`/`pipx`, but are not continuously validated
yet. The dashboard is a local web UI opened by `pctx gui` (currently in Spanish).

## CLI at a glance

| Command | What it does |
| --- | --- |
| `pctx init` / `scan` | Create memory and refresh verified facts |
| `pctx export` | Compile `PROJECT_CONTEXT.md` |
| `pctx context --task` | Build a task-scoped context pack |
| `pctx brief` | Short objective/next step/constraints/blockers brief |
| `pctx record` / `decision` | Add durable knowledge |
| `pctx handoff` | Save, verify or resume a session handoff |
| `pctx task` | Start, checkpoint or finish resumable work |
| `pctx plan` | Goals, checklists, difficulty, risk and reviews |
| `pctx coordinate` | Cooperative leases for tasks and paths |
| `pctx verify` | Preview or explicitly run a recorded check |
| `pctx lookup` / `expand` / `neighbors` | Budgeted retrieval over records |
| `pctx mcp serve` | MCP server over stdio |
| `pctx integrate` | Write MCP config for a client |
| `pctx adapters sync` | Update `AGENTS.md`, `CLAUDE.md`, etc. |
| `pctx doctor` | Health, drift and security checks |
| `pctx gui` | Local dashboard on `127.0.0.1` |
| `pctx backup` / `history` | Private backups and record revisions |

Full command help: `pctx <command> --help`.

## Security and privacy

- Everything runs locally. The dashboard binds to `127.0.0.1` and requires a
  per-session token; there is no cloud component.
- Transcripts, internal reasoning and routine tool output are not stored.
  `.project-context/.private/` and `.cache/` are excluded from version control.
- Secret-like content (private keys, provider tokens, password assignments) is
  rejected before it can be written to a canonical record.
- Signed/verified source is not executed by `scan`; stored check commands run
  only on an explicit `pctx verify --run` or request.
- Repository content is treated as **data**, not as instructions with authority.

## Status and limits

PCTX is **0.7.1 (beta)**. It is honest about what it cannot do:

- The scanner is static and best-effort; it does not infer full program
  semantics or guarantee complete coverage.
- Leases coordinate cooperative agents; they do not block editors at the OS
  level.
- `verified` means evidence was current and a recorded review covered the
  criteria — not that an independent audit happened.
- The GUI is Spanish-only today; the CLI, generated context and MCP tools are in
  English.
- Python 3.10+ on Linux is the tested path. Windows and macOS need validation.

## Documentation

- [Usage guide (ES)](docs/GUIA_USO.md) · [0.7 workflow](docs/USO_0.7.md) ·
  [0.7.1 fixes](docs/USO_0.7.1.md)
- [Integrations and MCP Master](docs/INTEGRACIONES.md)
- [Goals and checklists](docs/CHECKLISTS_0.5.md) ·
  [Coordination between AIs](docs/COORDINACION_0.6.md)
- [Retrieval and local embeddings](docs/RECUPERACION_0.4.md)
- [Changelog](CHANGELOG.md) · [Validation history](docs/README.md)

## Contributing

Bug reports, reproducible examples and focused pull requests are welcome. See
[CONTRIBUTING.md](CONTRIBUTING.md). Run the suite before sending changes:

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest -q
```

## License

MIT — see [LICENSE](LICENSE). PCTX is not affiliated with Anthropic, OpenAI,
Google or any editor vendor.
