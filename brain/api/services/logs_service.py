"""brain/api/services/logs_service.py — Structured log stream with secret redaction and sanitized support bundle.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import List, Optional
import zipfile

from brain.api.models import LogItem
from brain.api.services.privacy_service import preview_redaction
from brain.api.services.system_service import get_repo_root


def get_log_dirs() -> List[Path]:
    dirs = []
    # 1. Temp claude-master-logs
    tmp_logs = Path(tempfile.gettempdir()) / "claude-master-logs"
    if tmp_logs.exists():
        dirs.append(tmp_logs)
    # 2. Workspace logs dir
    repo_logs = get_repo_root() / "logs"
    if repo_logs.exists():
        dirs.append(repo_logs)
    return dirs


def get_recent_logs(
    level: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 100,
) -> List[LogItem]:
    log_dirs = get_log_dirs()
    items: List[LogItem] = []

    for ldir in log_dirs:
        for f in ldir.glob("*.log"):
            src_name = f.stem
            if source and source.lower() not in src_name.lower():
                continue
            try:
                lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
                for line in lines[-limit:]:
                    if not line.strip():
                        continue
                    lvl = "INFO"
                    if "ERROR" in line or "ERR" in line:
                        lvl = "ERROR"
                    elif "WARN" in line:
                        lvl = "WARN"
                    elif "DEBUG" in line:
                        lvl = "DEBUG"

                    if level and level.upper() != lvl:
                        continue

                    # Mask secrets in logs
                    sanitized = preview_redaction(line).redacted_text
                    ts = time.strftime("%Y-%m-%d %H:%M:%S")
                    items.append(
                        LogItem(
                            timestamp=ts,
                            level=lvl,
                            source=src_name,
                            message=sanitized,
                        )
                    )
            except Exception:
                pass

    return items[-limit:]


def create_sanitized_support_bundle() -> Path:
    """Generate a sanitized ZIP support bundle containing redacted logs and diagnosis."""
    bundle_path = Path(tempfile.gettempdir()) / f"claude_master_bundle_{int(time.time())}.zip"
    log_dirs = get_log_dirs()

    with zipfile.ZipFile(str(bundle_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for ldir in log_dirs:
            for f in ldir.glob("*.log*"):
                try:
                    raw_text = f.read_text(encoding="utf-8", errors="replace")
                    sanitized = preview_redaction(raw_text).redacted_text
                    zf.writestr(f"logs/{f.name}", sanitized)
                except Exception:
                    pass

        # Write readme / metadata
        manifest = f"claude-master sanitized support bundle\nGenerated at: {time.asctime()}\nOS: {sys.platform}\n"
        zf.writestr("MANIFEST.txt", manifest)

    return bundle_path
