"""brain/paths.py — cross-platform default paths (rewrite).

The original code hardcoded /tmp/... everywhere, which breaks on Windows
and on machines where TMPDIR differs. This module centralises defaults:

- env var wins if set (CLAUDE_BRAIN_DB, CLAUDE_BRAIN_SOCKET, CLAUDE_BRAIN_LOG_DIR)
- else os-specific temp dir via tempfile.gettempdir()
- callers must ensure parent dirs exist before opening files.

Usage:
    from brain.paths import default_db_path, default_socket_path, default_log_dir
"""

from __future__ import annotations

import os
import tempfile


def _tmp() -> str:
    return tempfile.gettempdir()


def default_db_path() -> str:
    return os.environ.get("CLAUDE_BRAIN_DB") or os.path.join(_tmp(), "claude_brain.db")


def default_socket_path() -> str:
    return os.environ.get("CLAUDE_BRAIN_SOCKET") or os.environ.get("BRAIN_SOCKET") or os.path.join(
        _tmp(), "claude_brain.sock"
    )


def default_log_dir() -> str:
    return os.environ.get("CLAUDE_BRAIN_LOG_DIR") or os.path.join(_tmp(), "claude-master-logs")


def ensure_parent(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
