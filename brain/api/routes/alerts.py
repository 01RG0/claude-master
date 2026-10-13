"""brain/api/routes/alerts.py — System health alerts, acknowledgement, and snooze.
"""

from __future__ import annotations

from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
import sqlite3

from brain.api.dependencies import get_db
from brain.api.models import AlertItem
from brain.api.services.alerts_service import get_alerts, acknowledge_alert, snooze_alert

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get("", response_model=List[AlertItem])
def get_alerts_endpoint(
    include_acknowledged: bool = Query(False),
    conn: sqlite3.Connection = Depends(get_db),
):
    return get_alerts(conn, include_acknowledged=include_acknowledged)


@router.post("/{alert_id}/acknowledge")
def ack_alert_endpoint(alert_id: str, conn: sqlite3.Connection = Depends(get_db)):
    ok = acknowledge_alert(conn, alert_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"ok": True, "alert_id": alert_id}


@router.post("/{alert_id}/snooze")
def snooze_alert_endpoint(
    alert_id: str,
    minutes: int = Query(60),
    conn: sqlite3.Connection = Depends(get_db),
):
    ok = snooze_alert(conn, alert_id, snooze_minutes=minutes)
    if not ok:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"ok": True, "alert_id": alert_id, "snoozed_minutes": minutes}
