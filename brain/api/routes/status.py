"""brain/api/routes/status.py — Status endpoint.
"""

from fastapi import APIRouter, Depends
import sqlite3

from brain.api.dependencies import get_db, get_brain_server
from brain.api.models import SystemStatusResponse
from brain.api.services.system_service import build_system_status

router = APIRouter(tags=["Status"])


@router.get("/status", response_model=SystemStatusResponse)
def get_system_status_endpoint(
    conn: sqlite3.Connection = Depends(get_db),
    brain_server = Depends(get_brain_server),
):
    return build_system_status(conn, brain_server=brain_server)
