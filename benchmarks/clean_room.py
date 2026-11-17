"""Small clean-room handoff benchmark for the PCTX alpha.

It intentionally uses only the generated task context after the records are
created.  The assertions are deterministic and can run without an LLM.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pctx.compile import compile_context, export_context
from pctx.architecture import refresh_architecture
from pctx.model import make_record
from pctx.scan import scan_project
from pctx.storage import init_context, upsert_record
from pctx.tasks import start_task


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="pctx-clean-room-"))
    (root / "package.json").write_text(json.dumps({"name": "auth-demo", "scripts": {"test": "pytest", "build": "python -m compileall src"}}), encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "auth.py").write_text("def create_session(user_id):\n    return user_id\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "payments.md").write_text("Payments are handled by a separate service.\n", encoding="utf-8")

    init_context(root, "auth-demo")
    scan_project(root)
    refresh_architecture(root)
    start_task(root, "Fix the authentication session", next_actions=["Run the auth tests"], origin="benchmark")
    upsert_record(root, make_record(
        record_type="constraint",
        record_id="constraint.auth.no-secrets",
        scope="auth",
        statement="Never commit session secrets or API key values.",
        state="user_asserted",
    ))
    upsert_record(root, make_record(
        record_type="decision",
        record_id="decision.auth.cookie",
        scope="auth",
        statement="Use an HttpOnly cookie for the browser session.",
        state="user_asserted",
        evidence=[{"kind": "file", "path": "src/auth.py", "content_hash": __import__("pctx.storage", fromlist=["sha256_file"]).sha256_file(root / "src/auth.py")}],
    ))
    upsert_record(root, make_record(
        record_type="note",
        record_id="note.payments.unrelated",
        scope="payments",
        statement="Payments use a separate service and are unrelated to this auth task.",
        state="user_asserted",
    ))
    export_context(root)
    task_text, info = compile_context(root, task="fix the authentication session without leaking secrets", budget=1800)
    required = ["constraint.auth.no-secrets", "decision.auth.cookie", "npm test", "flowchart LR", "Active task"]
    missing = [item for item in required if item not in task_text]
    if missing:
        raise SystemExit(f"missing required context: {missing}")
    if "api key values" not in task_text.lower():
        raise SystemExit("security constraint was not compiled")
    if "ghp_" in task_text or "sk-" in task_text:
        raise SystemExit("secret-like value leaked")
    print(f"clean-room: PASS; task_tokens={info['approximate_tokens']}; records={info['records_included']}; root={root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
