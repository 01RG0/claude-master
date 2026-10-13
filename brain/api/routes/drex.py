"""brain/api/routes/drex.py — Drex judge toggles, status, and accuracy log.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
import sqlite3

from brain.api.dependencies import get_db
from brain.api.models import DrexStatusResponse, DrexUpdateRequest
from brain.api.services.drex_service import get_drex_status, update_drex_config

router = APIRouter(prefix="/drex", tags=["Drex"])


@router.get("", response_model=DrexStatusResponse)
def get_drex_endpoint(conn: sqlite3.Connection = Depends(get_db)):
    return get_drex_status(conn)


@router.put("", response_model=DrexStatusResponse)
def update_drex_endpoint(req: DrexUpdateRequest, conn: sqlite3.Connection = Depends(get_db)):
    return update_drex_config(req, conn)
