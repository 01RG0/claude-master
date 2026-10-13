"""brain/auth.py — local auth token management for claude-master.
Delegates to brain.api.security for unified token management and constant-time verification.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from brain.api.security import (
    get_or_create_auth_token as get_or_create_token,
    verify_token,
    get_token_paths,
)


def load_token() -> Optional[str]:
    """Read existing token from candidate paths or environment."""
    for p in get_token_paths():
        if p.is_file():
            try:
                content = p.read_text(encoding="utf-8").strip()
                if content:
                    return content
            except OSError:
                pass
    return None
