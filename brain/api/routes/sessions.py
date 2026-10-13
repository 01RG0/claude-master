"""brain/api/routes/sessions.py — Session metrics and historical session breakdown.
"""

from __future__ import annotations

from typing import List
from fastapi import APIRouter, Depends, Query
import sqlite3

from brain.api.dependencies import get_db
from brain.api.models import SessionItem
from brain.api.services.requests_service import get_sessions_summary

router = APIRouter(prefix="/sessions", tags=["Sessions"])


@router.get("", response_model=List[SessionItem])
def get_sessions_endpoint(limit: int = Query(50), conn: sqlite3.Connection = Depends(get_db)):
    return get_sessions_summary(conn, limit=limit)
