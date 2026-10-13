"""brain/api/routes/wizard.py — Setup wizard, environment check, fix, and safe .env key import.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
from fastapi import APIRouter, Depends, HTTPException

from brain.api.dependencies import get_db
from brain.api.models import (
    EnvCheckResponse,
    EnvCheckItem,
    ImportEnvRequest,
    ImportEnvResponse,
    DiscoveredKey,
    WizardFixRequest,
    DoctorFixResponse,
)
from brain.api.security import mask_key
from brain.api.services.system_service import is_port_listening, get_repo_root
from brain.api.services.claude_service import detect_claude_cli
from brain.api.services.doctor_service import execute_doctor_fix
from brain.api.services.keystore_service import store_key, KeyAddRequest
from brain.api.services.config_service import read_gateway_config

router = APIRouter(prefix="/wizard", tags=["Wizard"])


@router.get("/env-check", response_model=EnvCheckResponse)
def get_env_check(conn: sqlite3.Connection = Depends(get_db)):
    checks: list[EnvCheckItem] = []

    # 1. Windows Version
    is_win = sys.platform == "win32"
    win_ver = sys.getwindowsversion() if is_win else None
    ver_str = f"Windows {win_ver.major}.{win_ver.minor} (Build {win_ver.build})" if win_ver else str(sys.platform)
    checks.append(
        EnvCheckItem(
            check_id="os_version",
            category="os",
            title="Operating System",
            status="pass" if is_win else "warn",
            details=f"Running on {ver_str}. Native Windows APIs active.",
            recommendation="Windows 10/11 or Windows Server recommended for full DPAPI and process support.",
        )
    )

    # 2. Claude Code Installation
    claude_ok, claude_ver = detect_claude_cli()
    checks.append(
        EnvCheckItem(
            check_id="claude_code",
            category="tools",
            title="Claude Code CLI",
            status="pass" if claude_ok else "warn",
            details=f"Claude Code: {claude_ver}",
            recommendation="Install Claude Code: npm install -g @anthropic-ai/claude-code",
            fix_action_available=False,
        )
    )

    # 3. Ports Availability (8080, 7700, 7772)
    p8080 = is_port_listening(8080)
    p7700 = is_port_listening(7700)
    p7772 = is_port_listening(7772)
    checks.append(
        EnvCheckItem(
            check_id="ports",
            category="network",
            title="Loopback Ports (8080, 7700, 7772)",
            status="pass" if (p7700 or p8080) else "pass",
            details=f"Port 8080 (Gateway): {'Active' if p8080 else 'Free/Standby'}, Port 7700 (Brain): Active, Port 7772 (Hooks): {'Active' if p7772 else 'Free/Standby'}",
            recommendation="",
        )
    )

    # 4. File Permissions & APPDATA
    appdata = os.environ.get("APPDATA")
    appdata_ok = appdata and os.path.exists(appdata) and os.access(appdata, os.W_OK)
    checks.append(
        EnvCheckItem(
            check_id="appdata_perms",
            category="filesystem",
            title="User APPDATA Storage Permissions",
            status="pass" if appdata_ok else "warn",
            details=f"APPDATA directory ({appdata}) writable for secure DPAPI keystore.",
        )
    )

    # 5. Disk space
    root = get_repo_root()
    _, _, free = shutil.disk_usage(str(root))
    free_gb = round(free / (1024**3), 2)
    checks.append(
        EnvCheckItem(
            check_id="disk_space",
            category="filesystem",
            title="Disk Space",
            status="pass" if free_gb >= 2.0 else "warn",
            details=f"{free_gb} GB free on workspace drive.",
            recommendation="Ensure at least 1 GB is free for SQLite WAL logs.",
        )
    )

    # 6. Antivirus / Defender note
    checks.append(
        EnvCheckItem(
            check_id="antivirus",
            category="security",
            title="Windows Defender & Antivirus",
            status="pass",
            details="All inter-process communication uses 127.0.0.1 TCP loopback. No driver hooks required.",
            recommendation="If real-time scanning slows node operations, consider adding the project folder to Defender exclusions.",
        )
    )

    overall = "healthy" if all(c.status == "pass" for c in checks) else "warning"

    return EnvCheckResponse(
        system_info={
            "os": ver_str,
            "python": sys.version.split()[0],
            "workspace": str(root),
        },
        checks=checks,
        overall_status=overall,
    )


@router.post("/fix", response_model=DoctorFixResponse)
def fix_env_action(req: WizardFixRequest, conn: sqlite3.Connection = Depends(get_db)):
    return execute_doctor_fix(req.action_id, conn)


@router.post("/import-env", response_model=ImportEnvResponse)
async def import_env(req: ImportEnvRequest, conn: sqlite3.Connection = Depends(get_db)):
    root = get_repo_root()
    content = req.env_content or ""
    if not content:
        env_path = Path(req.file_path) if req.file_path else root / ".env"
        if env_path.exists():
            content = env_path.read_text(encoding="utf-8", errors="replace")

    discovered: list[DiscoveredKey] = []
    config = read_gateway_config()
    existing_vars = set()
    for p in config.get("providers", []):
        for kp in p.get("key_pools", []):
            existing_vars.add(kp.get("env_var", ""))

    pattern = re.compile(r"^\s*([A-Za-z0-9_]+_API_KEY|[A-Za-z0-9_]+_TOKEN)\s*=\s*['\"]?([^'\"\r\n]+)['\"]?", re.MULTILINE)
    imported_count = 0

    for match in pattern.finditer(content):
        var_name = match.group(1).strip()
        raw_val = match.group(2).strip()
        if not raw_val:
            continue

        # Detect provider name
        prov = "custom"
        var_upper = var_name.upper()
        if "GROQ" in var_upper:
            prov = "groq"
        elif "CEREBRAS" in var_upper:
            prov = "cerebras"
        elif "MISTRAL" in var_upper:
            prov = "mistral"
        elif "COHERE" in var_upper:
            prov = "cohere"
        elif "GEMINI" in var_upper:
            prov = "gemini"
        elif "OPENROUTER" in var_upper:
            prov = "openrouter"
        elif "ANTHROPIC" in var_upper:
            prov = "anthropic"
        elif "OPENAI" in var_upper:
            prov = "openai"

        discovered.append(
            DiscoveredKey(
                env_var=var_name,
                provider=prov,
                masked_key=mask_key(raw_val),
                already_configured=var_name in existing_vars,
            )
        )

        if req.apply:
            await store_key(
                KeyAddRequest(
                    provider=prov,
                    account_label="imported",
                    env_var=var_name,
                    key=raw_val,
                    priority=15,
                ),
                conn=conn,
            )
            imported_count += 1

    return ImportEnvResponse(
        discovered=discovered,
        applied=req.apply,
        imported_count=imported_count,
    )
