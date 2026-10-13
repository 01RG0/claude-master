"""brain/api/routes/privacy.py — Data rules, secret & PII redaction, and redaction preview.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
import sqlite3

from brain.api.dependencies import get_db
from brain.api.models import (
    PrivacyConfigResponse,
    PrivacyUpdateRequest,
    PrivacyPreviewRequest,
    PrivacyPreviewResponse,
)
from brain.api.services.privacy_service import (
    get_privacy_config,
    update_privacy_config,
    preview_redaction,
)

router = APIRouter(prefix="/privacy", tags=["Privacy"])


@router.get("", response_model=PrivacyConfigResponse)
def get_privacy_endpoint(conn: sqlite3.Connection = Depends(get_db)):
    return get_privacy_config(conn)


@router.put("", response_model=PrivacyConfigResponse)
def update_privacy_endpoint(req: PrivacyUpdateRequest, conn: sqlite3.Connection = Depends(get_db)):
    return update_privacy_config(req, conn)


@router.post("/preview", response_model=PrivacyPreviewResponse)
def preview_privacy_endpoint(req: PrivacyPreviewRequest, conn: sqlite3.Connection = Depends(get_db)):
    return preview_redaction(req.text, conn)
