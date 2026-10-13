"""brain/api/routes/bypass.py — Emergency bypass toggle and state.
"""

from fastapi import APIRouter, Depends
import sqlite3

from brain.api.dependencies import get_db
from brain.api.models import BypassStateResponse, BypassToggleRequest
from brain.api.services.system_service import get_bypass_state, set_bypass_state

router = APIRouter(tags=["Bypass"])


@router.get("/bypass", response_model=BypassStateResponse)
def get_bypass(conn: sqlite3.Connection = Depends(get_db)):
    return get_bypass_state(conn)


@router.post("/bypass", response_model=BypassStateResponse)
def toggle_bypass(req: BypassToggleRequest, conn: sqlite3.Connection = Depends(get_db)):
    return set_bypass_state(conn, enabled=req.enabled, reason=req.reason)
