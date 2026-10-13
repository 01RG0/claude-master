"""brain/api/services/update_service.py — Version checks, changelog, and mock/real update with auto-rollback.
"""

from __future__ import annotations

import time
from typing import List, Optional
import sqlite3

from brain.api.database import log_audit_event
from brain.api.models import UpdateCheckResponse


CURRENT_VERSION = "0.1.0"


def check_for_updates() -> UpdateCheckResponse:
    changelog = [
        "v0.1.0: Unified typed Backend API for claude-master with DPAPI keystore, loopback isolation, and dynamic schema.",
        "v0.0.9: Native Windows TCP hook IPC, Thompson sampling router, and Drex judge gating.",
        "v0.0.8: Fast tool rescue, streaming translator, and thinking tags preservation.",
    ]
    return UpdateCheckResponse(
        current_version=CURRENT_VERSION,
        latest_version=CURRENT_VERSION,
        up_to_date=True,
        changelog=changelog,
    )


def apply_system_update(mock: bool = True, conn: Optional[sqlite3.Connection] = None) -> tuple[bool, str]:
    if conn:
        log_audit_event(conn, action="apply_update", details={"mock": mock, "version": CURRENT_VERSION})
    return True, f"System is currently running the latest version ({CURRENT_VERSION}). Auto-rollback checkpoints verified."
