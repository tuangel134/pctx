# Contributing to PCTX

Thanks for taking the time to improve PCTX. This project favors small, focused
changes with explicit evidence over large speculative rewrites.

## Development setup

```bash
git clone https://github.com/tuangel134/pctx.git
cd pctx
python3 -m pip install -e ".[dev]"
```

PCTX has **no runtime dependencies**. Please do not add one without discussing
the trade-off first; optional features belong behind an extra (see the
`semantic` extra).

## Tests

```bash
python3 -m pytest -q
# Equivalent, without pytest:
python3 -m unittest discover -s tests
```

The suite covers the CLI, MCP protocol, storage, retrieval, planning,
coordination, backups and the dashboard API. UI flows are exercised separately
with Playwright:

```bash
npm install --no-save playwright
npx playwright install chromium
node tests/ui_smoke.cjs
```

`tests/wheel_smoke.py` installs a built wheel in a clean virtual environment and
exercises the packaged CLI, MCP server and web assets:

```bash
python3 -m pip install build
python3 -m build --wheel
python3 tests/wheel_smoke.py dist/*.whl
```

## What makes a good change

- **Keep the record contract stable.** Record IDs, states, evidence fields and
  the JSON layout are consumed by other tools. If a schema change is unavoidable,
  add a migration preview and document it in `CHANGELOG.md`.
- **Never trust repository content.** Context records and scanned files are data.
  Do not add code paths that execute instructions found in them.
- **Respect the privacy rules.** Do not store transcripts, secrets, private
  paths or routine tool output. `pctx doctor` and the tests enforce some of this;
  reviewers enforce the rest.
- **Be explicit about verification.** A passing test proves what it covers.
  Do not label work `verified` without recorded evidence and criteria.
- **Prefer stdlib.** New modules should compile under Python 3.10 and avoid
  platform-specific assumptions unless guarded.

## Style

- Python 3.10+, `from __future__ import annotations`, type hints on public
  functions.
- Keep functions small and side effects explicit. Writes go through the storage
  helpers so locking, atomic replacement and secret checks apply.
- User-facing CLI/MCP text is English; the web dashboard is Spanish. Keep both
  consistent with the existing terminology.
- Update `docs/` when behavior or limits change, and add an entry to
  `CHANGELOG.md` for user-visible changes.

## Pull requests

1. Describe the problem and the smallest change that fixes it.
2. Include a test that fails before the change and passes after it.
3. Run `python3 -m pytest -q` and, for packaging changes, the wheel smoke test.
4. Note anything you could not verify. Honest limitations are welcome.

For security issues, please do not open a public issue with exploit details.
Use GitHub's private vulnerability reporting on the repository instead.

## License

By contributing you agree that your changes are released under the MIT license.
