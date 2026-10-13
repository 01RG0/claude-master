"""brain/api/services/backup_service.py — Database, configuration, and keystore backup and restore engine.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sqlite3
import time
from typing import List, Optional
import zipfile

from brain.api.database import log_audit_event
from brain.api.models import BackupItem
from brain.api.services.system_service import get_repo_root
from brain.api.services.config_service import get_gateway_config_path
from brain.api.services.keystore_service import get_keystore_path
from brain.paths import default_db_path


def get_backups_dir() -> Path:
    p = get_repo_root() / ".backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def list_backups(conn: sqlite3.Connection) -> List[BackupItem]:
    items: List[BackupItem] = []
    try:
        rows = conn.execute("SELECT * FROM backups_meta ORDER BY created_at DESC").fetchall()
        for r in rows:
            items.append(
                BackupItem(
                    backup_id=r["backup_id"],
                    file_path=r["file_path"],
                    size_bytes=r["size_bytes"],
                    notes=r["notes"],
                    created_at=r["created_at"],
                )
            )
    except Exception:
        pass
    return items


def create_system_backup(conn: sqlite3.Connection, notes: Optional[str] = None) -> BackupItem:
    now = int(time.time() * 1000)
    backup_id = f"backup_{now}"
    b_dir = get_backups_dir()
    zip_path = b_dir / f"{backup_id}.zip"

    db_file = Path(default_db_path())
    cfg_file = get_gateway_config_path()
    ks_file = get_keystore_path()

    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
        if db_file.exists():
            # Flush WAL checkpoint before copying DB
            try:
                conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            except Exception:
                pass
            zf.write(str(db_file), arcname="brain.db")
        if cfg_file.exists():
            zf.write(str(cfg_file), arcname="config.json")
        if ks_file.exists():
            zf.write(str(ks_file), arcname="keys.json")

    size = zip_path.stat().st_size
    conn.execute(
        "INSERT INTO backups_meta (backup_id, file_path, size_bytes, notes, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (backup_id, str(zip_path), size, notes or "System backup", now),
    )
    conn.commit()
    log_audit_event(conn, action="create_backup", details={"backup_id": backup_id, "size_bytes": size})

    return BackupItem(
        backup_id=backup_id,
        file_path=str(zip_path),
        size_bytes=size,
        notes=notes or "System backup",
        created_at=now,
    )


def restore_system_backup(conn: sqlite3.Connection, backup_id: str) -> bool:
    row = conn.execute("SELECT file_path FROM backups_meta WHERE backup_id = ?", (backup_id,)).fetchone()
    if not row:
        return False

    zip_path = Path(row["file_path"])
    if not zip_path.exists():
        return False

    with zipfile.ZipFile(str(zip_path), "r") as zf:
        # Extract config.json
        if "config.json" in zf.namelist():
            cfg_content = zf.read("config.json")
            get_gateway_config_path().write_bytes(cfg_content)
        # Extract keys.json
        if "keys.json" in zf.namelist():
            ks_content = zf.read("keys.json")
            get_keystore_path().write_bytes(ks_content)

    log_audit_event(conn, action="restore_backup", details={"backup_id": backup_id})
    return True
