"""
desktop/service_manager.py — Process lifecycle and system actions for claude-master.
"""

from __future__ import annotations
import os
import subprocess
import sys
import time
import urllib.request
import json
import logging
from pathlib import Path
import psutil

logger = logging.getLogger("desktop.service_manager")
REPO_ROOT = Path(__file__).resolve().parent.parent


def get_repo_root() -> Path:
    return REPO_ROOT


def start_system() -> bool:
    """Launch claude-master stack (brain + gateway + watchdog)."""
    root = get_repo_root()
    start_ps1 = root / "scripts" / "start.ps1"
    if start_ps1.exists():
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", str(start_ps1),
        ]
        # Spawn detached in background
        subprocess.Popen(
            cmd,
            cwd=str(root),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True

    # Fallback: start brain server directly
    subprocess.Popen(
        [sys.executable, "-m", "brain.server"],
        cwd=str(root),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
    )
    return True


def stop_system() -> int:
    """Stop all running claude-master components."""
    stopped = 0
    targets = ["gateway.exe", "watchdog.exe"]
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info["name"] or "").lower()
            cmdline = " ".join(proc.info["cmdline"] or [])
            if name in targets or ("python" in name and "brain.server" in cmdline):
                proc.terminate()
                stopped += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return stopped


def restart_system() -> bool:
    stop_system()
    time.sleep(1.0)
    return start_system()


def toggle_bypass() -> bool:
    """Toggle the Emergency Bypass mode in the running Brain or database."""
    # Try HTTP endpoint first
    try:
        url = "http://127.0.0.1:7700/api/v1/system/bypass"
        req = urllib.request.Request(url, headers={"User-Agent": "cm-desktop-tray/1.0"})
        current = False
        try:
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                current = bool(data.get("enabled", False))
        except Exception:
            current = False

        new_state = not current
        payload = json.dumps({"enabled": new_state, "reason": "Toggled via Desktop System Tray"}).encode("utf-8")
        post_req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "cm-desktop-tray/1.0"},
            method="POST"
        )
        with urllib.request.urlopen(post_req, timeout=2.0) as resp:
            return new_state
    except Exception as exc:
        logger.warning("Failed to toggle bypass via HTTP: %s", exc)

    # Fallback to direct sqlite setting
    try:
        from brain.paths import default_db_path
        from brain.api.database import get_db_connection
        from brain.api.services.system_service import get_bypass_state, set_bypass_state
        conn = get_db_connection(default_db_path())
        st = get_bypass_state(conn)
        res = set_bypass_state(conn, not st.enabled, reason="Toggled via Desktop System Tray")
        conn.close()
        return res.enabled
    except Exception as exc2:
        logger.error("Failed to toggle bypass in DB: %s", exc2)
        return False


def run_doctor_repair() -> dict:
    """Execute doctor diagnostics and auto-fixes, returning summary."""
    try:
        from brain.paths import default_db_path
        from brain.api.database import get_db_connection
        from brain.api.services.doctor_service import run_doctor_checks, execute_doctor_fix
        conn = get_db_connection(default_db_path())
        report = run_doctor_checks(conn)
        fixed_count = 0
        for chk in report.checks:
            if chk.status in ("warn", "fail") and chk.can_auto_fix:
                res = execute_doctor_fix(chk.check_id, conn)
                if res.fixed:
                    fixed_count += 1
        # Re-run after fix
        final_report = run_doctor_checks(conn)
        conn.close()
        return {
            "overall_status": final_report.overall_status,
            "pass_count": final_report.pass_count,
            "warn_count": final_report.warn_count,
            "fail_count": final_report.fail_count,
            "fixed_count": fixed_count,
        }
    except Exception as exc:
        logger.error("Doctor run failed: %s", exc)
        return {"error": str(exc)}
