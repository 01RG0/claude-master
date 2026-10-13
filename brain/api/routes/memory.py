"""brain/api/routes/memory.py — Brain memory, lessons, episodic recall, and decay.
"""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
import sqlite3

from brain.api.dependencies import get_db
from brain.api.models import (
    MemoryQueryResponse,
    MemorySnapshotResponse,
)
from brain.api.services.memory_service import (
    query_memory,
    apply_confidence_decay,
    toggle_ab_learning,
    create_memory_snapshot,
    rollback_memory_snapshot,
)

router = APIRouter(prefix="/brain/memory", tags=["Memory"])


@router.get("", response_model=MemoryQueryResponse)
def get_memory_endpoint(
    q: Optional[str] = Query(None),
    limit: int = Query(50),
    conn: sqlite3.Connection = Depends(get_db),
):
    return query_memory(conn, query=q, limit=limit)


@router.post("/decay")
def decay_memory_endpoint(rate: float = Query(0.05), conn: sqlite3.Connection = Depends(get_db)):
    updated = apply_confidence_decay(conn, rate=rate)
    return {"ok": True, "decay_rate": rate, "lessons_updated": updated}


@router.post("/toggle-ab")
def toggle_ab_endpoint(conn: sqlite3.Connection = Depends(get_db)):
    state = toggle_ab_learning(conn)
    return {"ok": True, "ab_learning_enabled": state}


@router.post("/snapshot", response_model=MemorySnapshotResponse)
def snapshot_memory_endpoint(notes: str = Query(""), conn: sqlite3.Connection = Depends(get_db)):
    return create_memory_snapshot(conn, notes=notes)


@router.post("/rollback")
def rollback_memory_endpoint(snapshot_id: str = Query(...), conn: sqlite3.Connection = Depends(get_db)):
    ok = rollback_memory_snapshot(conn, snapshot_id=snapshot_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return {"ok": True, "restored_snapshot": snapshot_id}
