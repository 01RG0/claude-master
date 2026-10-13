"""
desktop/status.py — Service health checker and status classifier.
"""

from __future__ import annotations
import urllib.request
import json
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("desktop.status")


@dataclass
class SystemStatus:
    color: str            # "green", "yellow", "red", "orange"
    label: str            # "Normal", "Degraded", "Stopped", "Emergency Bypass"
    brain_healthy: bool
    gateway_healthy: bool
    bypass_active: bool
    details: str = ""


def check_brain_health(url: str = "http://127.0.0.1:7700/health", timeout_s: float = 1.0) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "cm-desktop-tray/1.0"})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.debug("Brain health probe failed: %s", exc)
    return None


def check_gateway_health(url: str = "http://127.0.0.1:8080/health", timeout_s: float = 1.0) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "cm-desktop-tray/1.0"})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.status in (200, 204)
    except Exception:
        # Also try root /
        try:
            req = urllib.request.Request("http://127.0.0.1:8080/", headers={"User-Agent": "cm-desktop-tray/1.0"})
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return resp.status in (200, 404)
        except Exception:
            return False


def check_bypass_active(brain_url: str = "http://127.0.0.1:7700", timeout_s: float = 1.0) -> bool:
    try:
        req = urllib.request.Request(f"{brain_url}/api/v1/system/bypass", headers={"User-Agent": "cm-desktop-tray/1.0"})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("enabled", False))
    except Exception:
        return False


def get_current_status(brain_port: int = 7700, gw_port: int = 8080) -> SystemStatus:
    """Determine the current unified status of claude-master."""
    brain_info = check_brain_health(f"http://127.0.0.1:{brain_port}/health")
    brain_healthy = brain_info is not None and brain_info.get("status") == "ok"
    gw_healthy = check_gateway_health(f"http://127.0.0.1:{gw_port}/health")
    bypass_active = check_bypass_active(f"http://127.0.0.1:{brain_port}") if brain_healthy else False

    if not brain_healthy and not gw_healthy:
        return SystemStatus(
            color="red",
            label="Stopped",
            brain_healthy=False,
            gateway_healthy=False,
            bypass_active=False,
            details="All services offline (brain & gateway stopped)",
        )

    if bypass_active:
        return SystemStatus(
            color="orange",
            label="Emergency Bypass",
            brain_healthy=brain_healthy,
            gateway_healthy=gw_healthy,
            bypass_active=True,
            details="Emergency Bypass active (AI guard rails disabled)",
        )

    if not brain_healthy or not gw_healthy:
        missing = "gateway" if not gw_healthy else "brain"
        return SystemStatus(
            color="yellow",
            label="Degraded",
            brain_healthy=brain_healthy,
            gateway_healthy=gw_healthy,
            bypass_active=False,
            details=f"Degraded operation ({missing} is offline)",
        )

    return SystemStatus(
        color="green",
        label="Normal",
        brain_healthy=True,
        gateway_healthy=True,
        bypass_active=False,
        details="All services running and healthy",
    )
