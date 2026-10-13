"""brain/api/services/alerts_service.py — System health alerts, acknowledgement, and snooze.
"""

from __future__ import annotations

import time
from typing import List, Optional
import sqlite3

from brain.api.database import log_audit_event
from brain.api.models import AlertItem


def get_alerts(conn: sqlite3.Connection, include_acknowledged: bool = False) -> List[AlertItem]:
    now = int(time.time() * 1000)
    clauses = ["(snoozed_until IS NULL OR snoozed_until <= ?)"]
    params = [now]

    if not include_acknowledged:
        clauses.append("acknowledged = 0")

    where_sql = " AND ".join(clauses)
    alerts: List[AlertItem] = []
    try:
        rows = conn.execute(
            f"SELECT * FROM system_alerts WHERE {where_sql} ORDER BY created_at DESC", params
        ).fetchall()
        for r in rows:
            alerts.append(
                AlertItem(
                    alert_id=r["alert_id"],
                    level=r["level"],
                    title=r["title"],
                    message=r["message"],
                    component=r["component"],
                    acknowledged=bool(r["acknowledged"]),
                    snoozed_until=r["snoozed_until"],
                    created_at=r["created_at"],
                )
            )
    except Exception:
        pass
    return alerts


def create_alert(conn: sqlite3.Connection, alert_id: str, level: str, title: str, message: str, component: str) -> None:
    now = int(time.time() * 1000)
    try:
        conn.execute(
            "INSERT INTO system_alerts (alert_id, level, title, message, component, acknowledged, snoozed_until, created_at) "
            "VALUES (?, ?, ?, ?, ?, 0, NULL, ?) ON CONFLICT(alert_id) DO UPDATE SET "
            "level = excluded.level, title = excluded.title, message = excluded.message, acknowledged = 0, snoozed_until = NULL",
            (alert_id, level, title, message, component, now),
        )
        conn.commit()
    except Exception:
        pass


def acknowledge_alert(conn: sqlite3.Connection, alert_id: str) -> bool:
    try:
        conn.execute("UPDATE system_alerts SET acknowledged = 1 WHERE alert_id = ?", (alert_id,))
        conn.commit()
        log_audit_event(conn, action="acknowledge_alert", details={"alert_id": alert_id})
        return True
    except Exception:
        return False


def snooze_alert(conn: sqlite3.Connection, alert_id: str, snooze_minutes: int = 60) -> bool:
    until = int((time.time() + snooze_minutes * 60) * 1000)
    try:
        conn.execute("UPDATE system_alerts SET snoozed_until = ? WHERE alert_id = ?", (until, alert_id))
        conn.commit()
        log_audit_event(conn, action="snooze_alert", details={"alert_id": alert_id, "snooze_minutes": snooze_minutes})
        return True
    except Exception:
        return False
