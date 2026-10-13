"""brain/api/services/claude_service.py — Claude Code CLI detection, config backup, routing setup, and undo.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Dict, Optional

from brain.api.database import log_audit_event
from brain.api.models import ClaudeStatusResponse


def get_claude_config_path() -> Path:
    # Standard Claude Code config is in ~/.claude.json or ~/.claude/settings.json
    home = Path.home()
    p1 = home / ".claude.json"
    if p1.exists():
        return p1
    p2 = home / ".claude" / "settings.json"
    if p2.exists():
        return p2
    return p1


def get_claude_backup_path() -> Path:
    return Path.home() / ".claude.json.bak_cm"


def detect_claude_cli() -> tuple[bool, str]:
    """Check if 'claude' CLI command exists in PATH."""
    claude_cmd = shutil.which("claude")
    if not claude_cmd:
        # Check npm global locations on Windows
        for candidate in [
            Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "claude" / "claude.exe",
        ]:
            if candidate.exists():
                claude_cmd = str(candidate)
                break

    if not claude_cmd:
        return False, "Not found in PATH"

    try:
        res = subprocess.run([claude_cmd, "--version"], capture_output=True, text=True, timeout=3)
        if res.returncode == 0:
            return True, res.stdout.strip()
    except Exception:
        pass
    return True, "Installed (version unknown)"


def get_claude_status() -> ClaudeStatusResponse:
    installed, version = detect_claude_cli()
    cfg_path = get_claude_config_path()
    bak_path = get_claude_backup_path()

    curr_base_url: Optional[str] = None
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            curr_base_url = data.get("anthropic_base_url") or data.get("apiBaseUrl")
        except Exception:
            pass

    env_base_url = os.environ.get("ANTHROPIC_BASE_URL")
    if env_base_url:
        curr_base_url = env_base_url

    is_routed = bool(curr_base_url and ("8080" in curr_base_url or "localhost" in curr_base_url))

    return ClaudeStatusResponse(
        installed=installed,
        version=version,
        config_file=str(cfg_path),
        current_base_url=curr_base_url,
        is_routed_to_gateway=is_routed,
        backup_file_exists=bak_path.exists(),
    )


def apply_gateway_routing() -> bool:
    """Backup original config and set gateway URL to http://127.0.0.1:8080."""
    cfg_path = get_claude_config_path()
    bak_path = get_claude_backup_path()

    data: Dict[str, Any] = {}
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            if not bak_path.exists():
                shutil.copyfile(cfg_path, bak_path)
        except Exception:
            pass

    data["anthropic_base_url"] = "http://127.0.0.1:8080"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True


def restore_claude_config() -> bool:
    """1-click undo: restore Claude Code original configuration."""
    cfg_path = get_claude_config_path()
    bak_path = get_claude_backup_path()
    if bak_path.exists():
        shutil.copyfile(bak_path, cfg_path)
        return True
    # If no backup, remove the anthropic_base_url key
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            data.pop("anthropic_base_url", None)
            cfg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return True
        except Exception:
            pass
    return False
