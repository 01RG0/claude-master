#!/usr/bin/env python3
"""Cross-platform bootstrap for claude-master (rewrite).

Replaces scripts/bootstrap.sh for Windows/macOS/Linux:
  python scripts/bootstrap.py

Steps: venv (if missing) -> pip install -e .[dev] + psutil -> go mod tidy
(where go exists) -> npm install (root + studio, where npm exists).
Never prints secrets. Idempotent.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(cmd, cwd=ROOT, check=True):
    print(f"$ {' '.join(str(c) for c in cmd)}")
    # On Windows, npm is a .cmd launcher. CreateProcess can't invoke batch
    # files directly; pass through cmd.exe instead of relying on PowerShell's
    # command resolver (which Python does not use).
    if os.name == "nt" and cmd and str(cmd[0]).lower() == "npm":
        npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm.cmd"
        cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", npm, *cmd[1:]]
    return subprocess.run(cmd, cwd=cwd, check=check)


def main() -> int:
    print("==> Python deps")
    run([sys.executable, "-m", "pip", "install", "-U", "pip", "setuptools", "wheel"])
    run([sys.executable, "-m", "pip", "install", "-e", ".[dev]", "psutil"], cwd=ROOT)

    print("==> Go modules")
    if shutil.which("go"):
        for mod in [ROOT, ROOT / "gateway", ROOT / "hookshim", ROOT / "watchdog"]:
            if (mod / "go.mod").exists():
                run(["go", "mod", "tidy"], cwd=mod, check=False)
    else:
        print("go not found; skipping Go modules (gateway tests will skip)")

    print("==> TypeScript / studio")
    if shutil.which("npm"):
        if (ROOT / "package.json").exists():
            run(["npm", "install", "--no-fund", "--no-audit"], cwd=ROOT, check=False)
        if (ROOT / "studio" / "package.json").exists():
            run(["npm", "install", "--no-fund", "--no-audit"], cwd=ROOT / "studio", check=False)
    else:
        print("npm not found; skipping studio install")

    print("==> Bootstrap complete")
    print(f"    Python: {sys.version.split()[0]}")
    go = shutil.which("go") or "missing"
    node = shutil.which("node") or "missing"
    print(f"    Go: {go}  Node: {node}")
    print("    Run tests with: python -m pytest -q")
    return 0


if __name__ == "__main__":
    sys.exit(main())
