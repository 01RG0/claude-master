"""brain/api/routes/update.py — Version checks, changelog, and mock/real update with auto-rollback.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
import sqlite3

from brain.api.dependencies import get_db
from brain.api.models import UpdateCheckResponse, UpdateApplyRequest
from brain.api.services.update_service import check_for_updates, apply_system_update

router = APIRouter(prefix="/update", tags=["Update"])


@router.get("", response_model=UpdateCheckResponse)
def check_update_endpoint():
    return check_for_updates()


@router.post("")
def apply_update_endpoint(req: UpdateApplyRequest, conn: sqlite3.Connection = Depends(get_db)):
    ok, msg = apply_system_update(mock=req.mock, conn=conn)
    return {"ok": ok, "message": msg}
