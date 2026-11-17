"""Build a dependency-free Python zipapp inside a project for sandboxed CLIs."""
from importlib.resources import files
import os
from pathlib import Path
import tempfile
import zipfile

from .storage import project_lock, safe_relative, init_context
from . import __version__


def build_portable(root: Path) -> dict:
    from .service import validate_workspace
    root = validate_workspace(root)
    with project_lock(root):
        init_context(root)
        destination = safe_relative(root, ".project-context/.runtime/pctx.pyz")
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".pctx-", dir=destination.parent)
        os.close(fd)
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("__main__.py", "from pctx.cli import main\nraise SystemExit(main())\n")
                package = files("pctx")
                for child in package.iterdir():
                    if child.name.endswith(".py") and child.is_file():
                        archive.writestr("pctx/" + child.name, child.read_bytes())
                for child in (package / "web").iterdir():
                    if child.is_file():
                        archive.writestr("pctx/web/" + child.name, child.read_bytes())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return {"path": str(destination), "version": __version__, "bytes": destination.stat().st_size,
                "usage": f"python3 {destination} --root {root.resolve()} context --task 'describe the task'"}
