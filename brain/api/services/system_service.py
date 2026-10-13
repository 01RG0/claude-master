"""brain/api/services/system_service.py — Process monitoring, lifecycle control, and system status.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time
from typing import Any, Dict, List, Optional
import psutil
import sqlite3

from brain.api.database import get_setting, set_setting, log_audit_event
from brain.api.models import (
    ProcessStatus,
    SystemStatusResponse,
    BypassStateResponse,
)


_PROCESS_START_TIME = time.time()


def get_repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def find_process_by_name(name_substring: str) -> Optional[psutil.Process]:
    """Find running psutil Process matching name substring."""
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            p_name = (p.info["name"] or "").lower()
            if name_substring.lower() in p_name:
                return p
            cmd = " ".join(p.info.get("cmdline") or []).lower()
            if name_substring.lower() in cmd:
                return p
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


_PORT_CACHE: dict[int, tuple[float, bool]] = {}


def is_port_listening(port: int, host: str = "127.0.0.1") -> bool:
    """Check if TCP port is active on loopback with 1s cache."""
    now = time.time()
    if port in _PORT_CACHE:
        cached_ts, cached_val = _PORT_CACHE[port]
        if now - cached_ts < 1.0:
            return cached_val

    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.02)
            res = (s.connect_ex((host, port)) == 0)
            _PORT_CACHE[port] = (now, res)
            return res
    except Exception:
        return False


def get_daemon_status() -> ProcessStatus:
    p = psutil.Process(os.getpid())
    mem = p.memory_info().rss / (1024 * 1024)
    cpu = p.cpu_percent(interval=None)
    uptime = time.time() - _PROCESS_START_TIME
    return ProcessStatus(
        name="brain_api",
        status="running",
        pid=p.pid,
        uptime_s=round(uptime, 2),
        memory_mb=round(mem, 2),
        cpu_percent=cpu,
        listen_port=7700,
    )


def get_gateway_status() -> ProcessStatus:
    listening = is_port_listening(8080)
    proc = find_process_by_name("gateway.exe") or find_process_by_name("gateway")
    if proc:
        try:
            mem = proc.memory_info().rss / (1024 * 1024)
            cpu = proc.cpu_percent(interval=None)
            uptime = time.time() - proc.create_time()
            return ProcessStatus(
                name="gateway",
                status="running" if listening else "starting",
                pid=proc.pid,
                uptime_s=round(uptime, 2),
                memory_mb=round(mem, 2),
                cpu_percent=cpu,
                listen_port=8080,
            )
        except Exception:
            pass
    return ProcessStatus(
        name="gateway",
        status="running" if listening else "stopped",
        pid=None,
        listen_port=8080 if listening else None,
    )


def get_watchdog_status() -> ProcessStatus:
    proc = find_process_by_name("watchdog.exe") or find_process_by_name("watchdog")
    if proc:
        try:
            mem = proc.memory_info().rss / (1024 * 1024)
            cpu = proc.cpu_percent(interval=None)
            uptime = time.time() - proc.create_time()
            return ProcessStatus(
                name="watchdog",
                status="running",
                pid=proc.pid,
                uptime_s=round(uptime, 2),
                memory_mb=round(mem, 2),
                cpu_percent=cpu,
            )
        except Exception:
            pass
    return ProcessStatus(
        name="watchdog",
        status="stopped",
        pid=None,
    )


def get_bypass_state(conn: sqlite3.Connection) -> BypassStateResponse:
    setting = get_setting(conn, "emergency_bypass", default={"enabled": False, "active_since": None, "reason": ""})
    return BypassStateResponse(
        enabled=bool(setting.get("enabled", False)),
        active_since=setting.get("active_since"),
        reason=setting.get("reason", ""),
    )


def set_bypass_state(conn: sqlite3.Connection, enabled: bool, reason: str = "") -> BypassStateResponse:
    now = int(time.time() * 1000) if enabled else None
    val = {"enabled": enabled, "active_since": now, "reason": reason}
    set_setting(conn, "emergency_bypass", val)
    log_audit_event(conn, action="toggle_bypass", details=val)
    return BypassStateResponse(enabled=enabled, active_since=now, reason=reason)


def get_error_rates(conn: sqlite3.Connection) -> Dict[str, float]:
    """Calculate error rate percentages over last 1h and last 24h."""
    now = int(time.time() * 1000)
    one_hour_ago = now - 3600 * 1000
    one_day_ago = now - 86400 * 1000

    def _calc_rate(since_ts: int) -> float:
        try:
            total = conn.execute(
                "SELECT COUNT(*) AS c FROM request_log WHERE created_at >= ?", (since_ts,)
            ).fetchone()["c"]
            if not total:
                return 0.0
            errs = conn.execute(
                "SELECT COUNT(*) AS c FROM request_log WHERE created_at >= ? AND outcome != 'success'",
                (since_ts,),
            ).fetchone()["c"]
            return round((errs / total) * 100, 2)
        except Exception:
            return 0.0

    return {
        "last_1h_pct": _calc_rate(one_hour_ago),
        "last_24h_pct": _calc_rate(one_day_ago),
    }


def get_active_sessions(conn: sqlite3.Connection) -> List[str]:
    """Distinct sessions active in the last 2 hours."""
    now = int(time.time() * 1000)
    since_ts = now - 2 * 3600 * 1000
    sessions = []
    try:
        rows = conn.execute(
            "SELECT DISTINCT session_id FROM episodic_events WHERE created_at >= ? AND session_id != '' LIMIT 20",
            (since_ts,),
        ).fetchall()
        for r in rows:
            if r["session_id"]:
                sessions.append(r["session_id"])
    except Exception:
        pass
    return sessions


def build_system_status(conn: sqlite3.Connection, brain_server: Any = None) -> SystemStatusResponse:
    daemon = get_daemon_status()
    gw = get_gateway_status()
    wd = get_watchdog_status()
    bypass = get_bypass_state(conn)
    err_rates = get_error_rates(conn)
    active_sessions = get_active_sessions(conn)

    # Brain stats
    nodes_count = 0
    episodic_count = 0
    hooks_handled = 0
    if brain_server:
        try:
            nodes_count = conn.execute("SELECT COUNT(*) AS c FROM brain_nodes").fetchone()["c"]
            episodic_count = conn.execute("SELECT COUNT(*) AS c FROM episodic_events").fetchone()["c"]
            hooks_handled = getattr(brain_server, "hooks_handled", 0)
        except Exception:
            pass

    # Spend calculation placeholder (integrated with budget service)
    hard_cap = get_setting(conn, "hard_cap_usd", default=50.0)
    spend_data = {
        "today_usd": 0.0,
        "month_usd": 0.0,
        "hard_cap_usd": hard_cap,
        "percent_of_cap": 0.0,
    }

    # Attention items
    attention = []
    if gw.status != "running":
        attention.append({
            "level": "warning",
            "component": "gateway",
            "message": "Gateway process is not running on port 8080. Claude Code cannot reach upstream providers.",
        })
    if bypass.enabled:
        attention.append({
            "level": "info",
            "component": "bypass",
            "message": f"Emergency Bypass is active: {bypass.reason or 'User activated'}",
        })
    if err_rates["last_1h_pct"] > 20.0:
        attention.append({
            "level": "critical",
            "component": "gateway",
            "message": f"High error rate detected in the last hour: {err_rates['last_1h_pct']}%",
        })

    return SystemStatusResponse(
        daemon=daemon,
        gateway=gw,
        watchdog=wd,
        brain={
            "status": "running",
            "nodes_count": nodes_count,
            "episodic_count": episodic_count,
            "hooks_handled": hooks_handled,
        },
        spend=spend_data,
        error_rates=err_rates,
        active_sessions=active_sessions,
        bypass_state=bypass.model_dump(),
        attention_list=attention,
    )


def control_service(action: str, component: str, conn: Optional[sqlite3.Connection] = None) -> tuple[bool, str, List[str]]:
    """Start, stop, or restart child processes."""
    root = get_repo_root()
    affected = []

    def _stop_process(name_sub: str) -> bool:
        p = find_process_by_name(name_sub)
        if p:
            try:
                p.terminate()
                p.wait(timeout=3)
                return True
            except Exception:
                try:
                    p.kill()
                    return True
                except Exception:
                    pass
        return False

    def _start_gw() -> bool:
        gw_exe = root / "gateway" / "gateway.exe"
        cfg = root / "gateway" / "config.json"
        if gw_exe.exists():
            subprocess.Popen([str(gw_exe), "--config", str(cfg)], cwd=str(root))
            return True
        return False

    def _start_wd() -> bool:
        wd_exe = root / "watchdog" / "watchdog.exe"
        if wd_exe.exists():
            subprocess.Popen([str(wd_exe)], cwd=str(root))
            return True
        return False

    if component in ("gateway", "all"):
        if action in ("stop", "restart"):
            if _stop_process("gateway.exe") or _stop_process("gateway"):
                affected.append("gateway")
        if action in ("start", "restart"):
            time.sleep(0.5)
            if _start_gw():
                if "gateway" not in affected:
                    affected.append("gateway")

    if component in ("watchdog", "all"):
        if action in ("stop", "restart"):
            if _stop_process("watchdog.exe") or _stop_process("watchdog"):
                affected.append("watchdog")
        if action in ("start", "restart"):
            time.sleep(0.5)
            if _start_wd():
                if "watchdog" not in affected:
                    affected.append("watchdog")

    if conn:
        log_audit_event(conn, action=f"control_{action}", details={"component": component, "affected": affected})

    msg = f"Action {action} on {component} finished successfully."
    return True, msg, affected
