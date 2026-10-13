"""brain/api/routes/control.py — Process lifecycle management.
"""

from fastapi import APIRouter, Depends, HTTPException
import sqlite3

from brain.api.dependencies import get_db
from brain.api.models import ControlRequest, ControlResponse
from brain.api.services.system_service import control_service

router = APIRouter(tags=["Control"])


@router.post("/control/{action}", response_model=ControlResponse)
def control_endpoint(
    action: str,
    req: ControlRequest = None,
    conn: sqlite3.Connection = Depends(get_db),
):
    if action not in ("start", "stop", "restart"):
        raise HTTPException(status_code=400, detail="Action must be start, stop, or restart")
    component = req.component if req else "all"
    ok, msg, affected = control_service(action, component, conn=conn)
    return ControlResponse(ok=ok, message=msg, affected=affected)
