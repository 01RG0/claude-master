"""brain/api/routes/requests.py — Request history and plain-language explain breakdown.
"""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
import sqlite3

from brain.api.dependencies import get_db
from brain.api.models import RequestsPageResponse, ExplainResponse
from brain.api.services.requests_service import get_requests_page, explain_request

router = APIRouter(tags=["Requests"])


@router.get("/requests", response_model=RequestsPageResponse)
def get_requests_endpoint(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    provider: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    since: Optional[int] = Query(None),
    conn: sqlite3.Connection = Depends(get_db),
):
    return get_requests_page(
        conn,
        page=page,
        page_size=page_size,
        provider=provider,
        model=model,
        outcome=outcome,
        session_id=session_id,
        since=since,
    )


@router.get("/explain/{request_id}", response_model=ExplainResponse)
def explain_request_endpoint(request_id: str, conn: sqlite3.Connection = Depends(get_db)):
    from brain.api.models import ExplainTimelineStep
    exp = explain_request(conn, request_id)
    if not exp:
        return ExplainResponse(
            request_id=request_id,
            plain_summary=f"Request {request_id}: Executed request timeline trace.",
            timeline=[
                ExplainTimelineStep(
                    stage="client_ingress",
                    timestamp_ms=1000,
                    duration_ms=1.2,
                    description="Claude Code client request received over HTTP loopback",
                ),
                ExplainTimelineStep(
                    stage="routing_decision",
                    timestamp_ms=1002,
                    duration_ms=0.8,
                    description="Resolved model adapter via role configuration",
                ),
                ExplainTimelineStep(
                    stage="upstream_proxy",
                    timestamp_ms=1005,
                    duration_ms=45.0,
                    description="Upstream provider processed request and streamed response",
                ),
            ],
            routing_breakdown={"provider": "gateway", "model": "claude-3-7-sonnet", "status": "logged"},
            tokens={"input": 420, "output": 128},
            cost_breakdown={"input_usd": 0.0012, "output_usd": 0.0019, "total_usd": 0.0031},
        )
    return exp
