"""brain/api/security.py — Security layer for claude-master Backend API.

Loopback-only enforcement, DPAPI encryption on Windows, auth token lifecycle,
origin validation, CSP headers, and secret masking.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import sys
from typing import Optional

# ---------------------------------------------------------------------------
# Windows DPAPI Implementation via ctypes
# ---------------------------------------------------------------------------

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32


def dpapi_protect(data: bytes) -> bytes:
    """Encrypt byte payload using Windows DPAPI (CurrentUser scope)."""
    if not _IS_WINDOWS:
        # Fallback for non-windows testing
        return b"NON_WIN:" + data

    if not data:
        return b""

    blob_in = _DATA_BLOB(
        len(data),
        ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_byte)),
    )
    blob_out = _DATA_BLOB()
    # CRYPTPROTECT_UI_FORBIDDEN = 0x1
    flags = 0x1
    if not _crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None, flags, ctypes.byref(blob_out)
    ):
        raise ctypes.WinError()

    try:
        res = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        return res
    finally:
        _kernel32.LocalFree(blob_out.pbData)


def dpapi_unprotect(data: bytes) -> bytes:
    """Decrypt byte payload using Windows DPAPI (CurrentUser scope)."""
    if not _IS_WINDOWS:
        if data.startswith(b"NON_WIN:"):
            return data[len(b"NON_WIN:"):]
        return data

    if not data:
        return b""

    blob_in = _DATA_BLOB(
        len(data),
        ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_byte)),
    )
    blob_out = _DATA_BLOB()
    flags = 0x1
    if not _crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, flags, ctypes.byref(blob_out)
    ):
        raise ctypes.WinError()

    try:
        res = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        return res
    finally:
        _kernel32.LocalFree(blob_out.pbData)


# ---------------------------------------------------------------------------
# Secret Masking & Hashing
# ---------------------------------------------------------------------------

def mask_key(secret: Optional[str]) -> str:
    """Mask a secret key so raw material is never returned across API.

    Returns: e.g. 'sk-ant-...a1b2' or '***'
    """
    if not secret:
        return ""
    secret = secret.strip()
    if len(secret) < 8:
        return "***"
    if secret.startswith("sk-ant-"):
        prefix = "sk-ant-"
        suffix = secret[-4:]
        return f"{prefix}...{suffix}"
    if secret.startswith("sk-"):
        prefix = "sk-"
        suffix = secret[-4:]
        return f"{prefix}...{suffix}"
    prefix = secret[:4]
    suffix = secret[-4:]
    return f"{prefix}...{suffix}"


def hash_key(secret: str) -> str:
    """Return hex SHA-256 hash of secret key (first 16 chars)."""
    if not secret:
        return ""
    h = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    return h[:16]


# ---------------------------------------------------------------------------
# Auth Token Lifecycle
# ---------------------------------------------------------------------------

_TOKEN_FILE_NAME = ".cm_token"


def _get_appdata_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        p = Path(appdata) / "claude-master"
    else:
        p = Path.home() / ".claude-master"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_token_paths() -> list[Path]:
    """Candidate paths for .cm_token, ordered by priority."""
    paths: list[Path] = [
        Path.cwd() / _TOKEN_FILE_NAME,
        Path(__file__).resolve().parent.parent.parent / _TOKEN_FILE_NAME,
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(Path(appdata) / "claude-master" / _TOKEN_FILE_NAME)
    paths.append(Path.home() / ".claude-master" / _TOKEN_FILE_NAME)
    return paths


def get_token_path() -> Path:
    # First existing path or default to repo root
    for p in get_token_paths():
        if p.exists():
            return p
    return Path(__file__).resolve().parent.parent.parent / _TOKEN_FILE_NAME


_CURRENT_TOKEN: Optional[str] = None


def get_or_create_auth_token() -> str:
    """Load or generate a per-install/session secret auth token."""
    global _CURRENT_TOKEN
    env_token = os.environ.get("CM_TOKEN") or os.environ.get("CLAUDE_MASTER_TOKEN")
    if env_token and env_token.strip():
        _CURRENT_TOKEN = env_token.strip()
        return _CURRENT_TOKEN

    if _CURRENT_TOKEN:
        return _CURRENT_TOKEN

    for candidate in get_token_paths():
        if candidate.exists():
            try:
                tok = candidate.read_text(encoding="utf-8").strip()
                if tok:
                    _CURRENT_TOKEN = tok
                    return tok
            except Exception:
                pass

    # Check APPDATA encrypted token
    enc_path = _get_appdata_dir() / "token.dpapi"
    if enc_path.exists() and _IS_WINDOWS:
        try:
            raw = enc_path.read_bytes()
            tok = dpapi_unprotect(raw).decode("utf-8").strip()
            if tok:
                _CURRENT_TOKEN = tok
                return tok
        except Exception:
            pass

    # Generate new random 32-byte urlsafe token
    new_token = secrets.token_urlsafe(32)
    _CURRENT_TOKEN = new_token

    try:
        token_path = get_token_path()
        token_path.write_text(new_token, encoding="utf-8")
        if _IS_WINDOWS:
            enc = dpapi_protect(new_token.encode("utf-8"))
            (_get_appdata_dir() / "token.dpapi").write_bytes(enc)
    except Exception:
        pass

    return _CURRENT_TOKEN


def verify_token(candidate: Optional[str]) -> bool:
    """Verify candidate token against current server token in constant time."""
    if not candidate:
        return False
    expected = get_or_create_auth_token()
    return hmac.compare_digest(candidate.strip(), expected)


# ---------------------------------------------------------------------------
# Loopback & Origin Checks
# ---------------------------------------------------------------------------

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


def is_loopback(host: Optional[str]) -> bool:
    """Return True if host is confirmed loopback."""
    if not host:
        return False
    clean = host.lower().strip()
    if clean in LOOPBACK_HOSTS:
        return True
    if clean.startswith("[") and "]" in clean:
        clean = clean[1:clean.index("]")]
        return clean in LOOPBACK_HOSTS
    if ":" in clean and not clean.startswith("::"):
        clean = clean.split(":")[0]
    return clean in LOOPBACK_HOSTS


def is_valid_origin(origin: Optional[str]) -> bool:
    """Reject non-localhost origins to guard against DNS rebinding & CSRF."""
    if not origin:
        return True  # No Origin header is normal for same-process/curl/CLI
    import urllib.parse
    try:
        parsed = urllib.parse.urlsplit(origin)
        hostname = (parsed.hostname or "").lower().strip()
        return hostname in ("localhost", "127.0.0.1", "::1")
    except Exception:
        return False
