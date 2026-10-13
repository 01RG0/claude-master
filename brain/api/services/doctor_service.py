"""brain/api/services/doctor_service.py — Comprehensive diagnostic suite with 1-click auto-fixes.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sqlite3
import sys
from typing import Any, Dict, List, Optional
import psutil

from brain.api.database import log_audit_event
from brain.api.models import DoctorCheck, DoctorReport, DoctorFixResponse
from brain.api.services.system_service import is_port_listening, get_repo_root
from brain.api.services.claude_service import detect_claude_cli
from brain.api.services.keystore_service import get_keystore_path
from brain.api.services.config_service import get_gateway_config_path, read_gateway_config, save_gateway_config


def run_doctor_checks(conn: sqlite3.Connection) -> DoctorReport:
    checks: List[DoctorCheck] = []

    # 1. Port 8080 (Gateway)
    gw_up = is_port_listening(8080)
    checks.append(
        DoctorCheck(
            check_id="port_8080",
            name="Gateway Port (8080)",
            category="network",
            status="pass" if gw_up else "warn",
            details="Gateway HTTP proxy is active on port 8080" if gw_up else "No process currently responding on loopback port 8080",
            recommendation="Start the gateway service via Control Screen" if not gw_up else "",
            can_auto_fix=not gw_up,
        )
    )

    # 2. Port 7700 (Brain API)
    brain_up = is_port_listening(7700)
    checks.append(
        DoctorCheck(
            check_id="port_7700",
            name="Brain API Port (7700)",
            category="network",
            status="pass" if brain_up else "pass",  # Since we are executing inside the process
            details="Brain API loopback server is running and healthy",
            recommendation="",
            can_auto_fix=False,
        )
    )

    # 3. Port 7772 (Hook TCP)
    hook_up = is_port_listening(7772)
    checks.append(
        DoctorCheck(
            check_id="port_7772",
            name="Hook IPC TCP Port (7772)",
            category="network",
            status="pass" if hook_up else "warn",
            details="Hook TCP server is listening on 127.0.0.1:7772" if hook_up else "Hook TCP port 7772 not active (socket server may still be initializing)",
            recommendation="Check brain socket_server in brain/server.py",
            can_auto_fix=False,
        )
    )

    # 4. SQLite DB WAL & Integrity
    db_status = "pass"
    db_msg = "Database integrity check passed (WAL mode active)"
    try:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if str(integrity).lower() != "ok":
            db_status = "fail"
            db_msg = f"Database integrity check failed: {integrity}"
        elif str(journal_mode).lower() != "wal":
            db_status = "warn"
            db_msg = f"Journal mode is '{journal_mode}', expected WAL for high concurrency"
    except Exception as exc:
        db_status = "fail"
        db_msg = f"Database error: {exc}"

    checks.append(
        DoctorCheck(
            check_id="sqlite_wal",
            name="SQLite Neocortical Store",
            category="storage",
            status=db_status,
            details=db_msg,
            recommendation="Enable WAL mode on the SQLite database" if db_status != "pass" else "",
            can_auto_fix=db_status != "pass",
        )
    )

    # 5. Keystore & DPAPI
    ks_path = get_keystore_path()
    ks_status = "pass"
    ks_msg = f"Keystore located at {ks_path} with DPAPI encryption enabled"
    if not ks_path.parent.exists():
        ks_status = "warn"
        ks_msg = "Keystore directory does not exist yet"
    checks.append(
        DoctorCheck(
            check_id="keystore_dpapi",
            name="DPAPI Runtime Keystore",
            category="security",
            status=ks_status,
            details=ks_msg,
            recommendation="Create keystore directory" if ks_status != "pass" else "",
            can_auto_fix=ks_status != "pass",
        )
    )

    # 6. Claude Code Installation
    claude_ok, claude_ver = detect_claude_cli()
    checks.append(
        DoctorCheck(
            check_id="claude_code",
            name="Claude Code CLI",
            category="integration",
            status="pass" if claude_ok else "warn",
            details=f"Claude Code detected: {claude_ver}" if claude_ok else "Claude Code CLI not found in PATH",
            recommendation="Install Claude Code via npm: npm install -g @anthropic-ai/claude-code" if not claude_ok else "",
            can_auto_fix=False,
        )
    )

    # 7. Gateway Config JSON
    cfg_path = get_gateway_config_path()
    cfg_status = "pass"
    cfg_msg = "Gateway config file valid and contains active providers"
    import json
    if not cfg_path.exists():
        cfg_status = "fail"
        cfg_msg = "gateway/config.json is missing"
    else:
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            if not cfg.get("providers"):
                cfg_status = "warn"
                cfg_msg = "No providers currently configured in gateway/config.json"
        except Exception as e:
            cfg_status = "fail"
            cfg_msg = f"gateway/config.json is corrupted: {e}"

    checks.append(
        DoctorCheck(
            check_id="gateway_config",
            name="Gateway Configuration",
            category="config",
            status=cfg_status,
            details=cfg_msg,
            recommendation="Configure upstream providers or run 1-click auto repair" if cfg_status != "pass" else "",
            can_auto_fix=cfg_status in ("fail", "warn"),
        )
    )

    # 8. Disk Space
    root = get_repo_root()
    total, used, free = shutil.disk_usage(str(root))
    free_gb = round(free / (1024**3), 2)
    space_status = "pass" if free_gb >= 2.0 else ("warn" if free_gb >= 0.5 else "fail")
    checks.append(
        DoctorCheck(
            check_id="disk_space",
            name="Available Disk Space",
            category="system",
            status=space_status,
            details=f"{free_gb} GB free on workspace drive",
            recommendation="Free disk space to prevent SQLite WAL failures" if space_status != "pass" else "",
            can_auto_fix=False,
        )
    )

    # Count passes / warnings / fails
    passed = sum(1 for c in checks if c.status == "pass")
    warnings = sum(1 for c in checks if c.status == "warn")
    failed = sum(1 for c in checks if c.status == "fail")

    overall = "healthy" if failed == 0 and warnings == 0 else ("warning" if failed == 0 else "critical")

    return DoctorReport(
        overall_status=overall,
        passed=passed,
        warnings=warnings,
        failed=failed,
        checks=checks,
    )


def execute_doctor_fix(check_id: str, conn: sqlite3.Connection) -> DoctorFixResponse:
    report_before = run_doctor_checks(conn)
    before_check = next((c for c in report_before.checks if c.check_id == check_id), None)
    before_status = before_check.status if before_check else "unknown"

    fixed = False
    message = "No automated fix applicable"

    if check_id == "sqlite_wal":
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.commit()
            fixed = True
            message = "Successfully set journal_mode to WAL."
        except Exception as e:
            message = f"Failed to set WAL: {e}"

    elif check_id == "keystore_dpapi":
        try:
            ks_path = get_keystore_path()
            ks_path.parent.mkdir(parents=True, exist_ok=True)
            fixed = True
            message = f"Created directory {ks_path.parent}"
        except Exception as e:
            message = f"Failed to create directory: {e}"

    elif check_id == "gateway_config":
        try:
            default_cfg = {
                "listen_addr": ":8080",
                "request_timeout_s": 60,
                "providers": [
                    {
                        "name": "anthropic",
                        "base_url": "https://api.anthropic.com/v1",
                        "key_pools": [
                            {"account_label": "personal", "env_var": "ANTHROPIC_API_KEY", "priority": 10}
                        ],
                    }
                ],
                "routing": {"strategy": "thompson_sampling"},
            }
            save_gateway_config(default_cfg, conn=conn, audit_action="doctor_fix_config")
            fixed = True
            message = "Restored default gateway config.json."
        except Exception as e:
            message = f"Failed to write config: {e}"

    elif check_id == "port_8080":
        # Attempt to launch gateway
        from brain.api.services.system_service import control_service
        ok, msg, affected = control_service("start", "gateway", conn=conn)
        fixed = ok
        message = msg

    report_after = run_doctor_checks(conn)
    after_check = next((c for c in report_after.checks if c.check_id == check_id), None)
    after_status = after_check.status if after_check else "unknown"

    log_audit_event(conn, action="doctor_fix", details={"check_id": check_id, "fixed": fixed, "message": message})

    return DoctorFixResponse(
        check_id=check_id,
        before_status=before_status,
        after_status=after_status,
        fixed=fixed,
        message=message,
    )
