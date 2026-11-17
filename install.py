"""Install PCTX for the current Linux user without changing system Python."""
from pathlib import Path
import os
import subprocess
import sys
import venv


def main():
    source = Path(__file__).resolve().parent
    destination = Path.home() / ".local/share/pctx/venv"
    if not (destination / "pyvenv.cfg").exists():
        if destination.exists() and any(destination.iterdir()):
            raise RuntimeError(f"Installation directory is not an empty virtual environment: {destination}")
        venv.EnvBuilder(with_pip=True).create(destination)
    python = destination / "bin/python"
    subprocess.run([str(python), "-m", "pip", "install", "--no-deps", "-e", str(source)], check=True)
    launcher = Path.home() / ".local/bin/pctx"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    executable = destination / "bin/pctx"
    if launcher.exists() or launcher.is_symlink():
        if launcher.resolve() != executable.resolve():
            raise RuntimeError(f"PCTX was installed, but another executable owns {launcher}; no replacement made")
    else:
        launcher.symlink_to(executable)
    subprocess.run([str(executable), "install-desktop"], check=True)
    print(f"PCTX installed. Open PCTX from the application menu, or run {executable} gui")
    print("Re-run this installer if the source directory moves.")


if __name__ == "__main__":
    try:
        if not sys.platform.startswith("linux"):
            raise RuntimeError("Use pip install . and pctx gui on non-Linux systems; this desktop installer is Linux-only")
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"PCTX installation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
