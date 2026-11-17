"""Absolute-path launcher, usable without a shell or a configured PYTHONPATH."""
from pathlib import Path
import sys

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from pctx.cli import main
    raise SystemExit(main())
