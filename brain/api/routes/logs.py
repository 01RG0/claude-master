"""brain/api/routes/logs.py — Structured log stream with secret redaction and support bundle export.
"""

from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from brain.api.models import LogItem
from brain.api.services.logs_service import get_recent_logs, create_sanitized_support_bundle

router = APIRouter(prefix="/logs", tags=["Logs"])


@router.get("", response_model=List[LogItem])
def get_logs_endpoint(
    level: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    return get_recent_logs(level=level, source=source, limit=limit)


@router.post("/bundle")
def export_bundle_endpoint():
    bundle_path = create_sanitized_support_bundle()
    return FileResponse(
        path=str(bundle_path),
        filename=bundle_path.name,
        media_type="application/zip",
    )
