"""brain/paths.py — cross-platform default paths (rewrite).

Windows-first: hooks use localhost TCP by default (no AF_UNIX, no file paths,
no spaces/backslash issues). POSIX keeps the Unix socket default for backward
compat, but the daemon also listens on TCP so either transport works.

- env var wins if set (CLAUDE_BRAIN_DB, CLAUDE_BRAIN_SOCKET, CLAUDE_BRAIN_TCP,
  CLAUDE_BRAIN_LOG_DIR)
- else os-specific temp dir via tempfile.gettempdir()
- callers must ensure parent dirs exist before opening files.

Usage:
    from brain.paths import default_db_path, default_socket_path, default_tcp_addr
"""

from __future__ import annotations

import os
import sys
import tempfile

DEFAULT_HOOK_TCP_HOST = "127.0.0.1"
DEFAULT_HOOK_TCP_PORT = 7772


def _tmp() -> str:
    return tempfile.gettempdir()


def default_db_path() -> str:
    return os.environ.get("CLAUDE_BRAIN_DB") or os.path.join(_tmp(), "claude_brain.db")


def default_socket_path() -> str:
    return os.environ.get("CLAUDE_BRAIN_SOCKET") or os.environ.get("BRAIN_SOCKET") or os.path.join(
        _tmp(), "claude_brain.sock"
    )


def default_tcp_addr() -> str:
    """Return 'host:port' for hook IPC. Env CLAUDE_BRAIN_TCP wins."""
    env = os.environ.get("CLAUDE_BRAIN_TCP") or os.environ.get("BRAIN_TCP")
    if env:
        return _normalise_tcp(env)
    return f"{DEFAULT_HOOK_TCP_HOST}:{DEFAULT_HOOK_TCP_PORT}"


def _normalise_tcp(addr: str) -> str:
    addr = addr.strip().strip("\"'")
    for prefix in ("tcp://", "TCP://"):
        if addr.startswith(prefix):
            addr = addr[len(prefix):]
            break
    if addr.startswith("["):
        return addr  # IPv6 literal, leave alone
    return addr


def is_tcp_endpoint(value: str) -> bool:
    """True for 'host:port', ':port', 'tcp://...' (not a filesystem path)."""
    v = (value or "").strip()
    if v.lower().startswith("tcp://"):
        return True
    if v.startswith("/") or v.startswith("\\\\") or v.startswith("\\\\?\\"):
        return False
    # Windows drive path C:\... or C:/... is a file, not TCP
    if len(v) >= 3 and v[1] == ":" and v[0].isalpha() and v[2] in ("\\", "/"):
        return False
    if v.startswith("\\\\.\\pipe\\"):
        return False
    # host:port — must have exactly one trailing :port with digits
    if ":" in v and v.rsplit(":", 1)[1].isdigit():
        return True
    return False


def split_tcp(addr: str) -> tuple[str, int]:
    """Split 'host:port' (or ':port') into (host, port). Raises ValueError."""
    a = _normalise_tcp(addr)
    if a.startswith(":"):
        return DEFAULT_HOOK_TCP_HOST, int(a[1:])
    host, _, port = a.rpartition(":")
    if not port.isdigit():
        raise ValueError(f"not a host:port TCP address: {addr!r}")
    return host or DEFAULT_HOOK_TCP_HOST, int(port)


def default_hook_is_tcp() -> bool:
    """Windows defaults to TCP; POSIX defaults to the Unix socket."""
    if os.environ.get("CLAUDE_BRAIN_TCP") or os.environ.get("BRAIN_TCP"):
        return True
    return sys.platform == "win32"


def default_log_dir() -> str:
    return os.environ.get("CLAUDE_BRAIN_LOG_DIR") or os.path.join(_tmp(), "claude-master-logs")


def ensure_parent(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
