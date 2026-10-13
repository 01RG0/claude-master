"""brain/api/database.py — Database management and audit/settings schema initialization.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Optional

from brain.paths import default_db_path
from brain.store.graph import GraphStore

EXTRA_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    details_json TEXT NOT NULL,
    client_ip TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS system_alerts (
    alert_id TEXT PRIMARY KEY,
    level TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    component TEXT NOT NULL,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    snoozed_until INTEGER,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS backups_meta (
    backup_id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    notes TEXT,
    created_at INTEGER NOT NULL
);
"""


def init_api_schema(conn: sqlite3.Connection) -> None:
    """Execute extra schema definitions idempotently."""
    conn.executescript(EXTRA_SCHEMA_SQL)
    conn.commit()


def log_audit_event(
    conn: sqlite3.Connection,
    action: str,
    actor: str = "local_user",
    details: Optional[dict[str, Any]] = None,
    client_ip: str = "127.0.0.1",
) -> None:
    """Record an audit trail event for any administrative or configuration change."""
    try:
        now = int(time.time() * 1000)
        details_json = json.dumps(details or {}, ensure_ascii=False)
        conn.execute(
            "INSERT INTO audit_log (action, actor, details_json, client_ip, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (action, actor, details_json, client_ip, now),
        )
        conn.commit()
    except Exception:
        pass


def get_setting(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    """Retrieve typed JSON setting from system_settings."""
    try:
        row = conn.execute(
            "SELECT value_json FROM system_settings WHERE key = ?", (key,)
        ).fetchone()
        if row:
            return json.loads(row["value_json"])
    except Exception:
        pass
    return default


def set_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    """Store typed JSON setting in system_settings."""
    try:
        now = int(time.time() * 1000)
        val_json = json.dumps(value, ensure_ascii=False)
        conn.execute(
            "INSERT INTO system_settings (key, value_json, updated_at) "
            "VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
            "value_json = excluded.value_json, updated_at = excluded.updated_at",
            (key, val_json, now),
        )
        conn.commit()
    except Exception:
        pass
