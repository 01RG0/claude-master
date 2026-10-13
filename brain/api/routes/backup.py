"""brain/api/routes/backup.py — Database, config, and keystore backup creation and restore.
"""

from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
import sqlite3

from brain.api.dependencies import get_db
from brain.api.models import BackupItem, BackupRestoreRequest
from brain.api.services.backup_service import (
    list_backups,
    create_system_backup,
    restore_system_backup,
)

router = APIRouter(prefix="/backup", tags=["Backup"])


@router.get("", response_model=List[BackupItem])
def get_backups_endpoint(conn: sqlite3.Connection = Depends(get_db)):
    return list_backups(conn)


@router.post("", response_model=BackupItem)
def create_backup_endpoint(
    notes: Optional[str] = Query(None),
    conn: sqlite3.Connection = Depends(get_db),
):
    return create_system_backup(conn, notes=notes)


@router.post("/restore")
def restore_backup_endpoint(req: BackupRestoreRequest, conn: sqlite3.Connection = Depends(get_db)):
    ok = restore_system_backup(conn, req.backup_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Backup archive not found or invalid")
    return {"ok": True, "restored_backup": req.backup_id}
