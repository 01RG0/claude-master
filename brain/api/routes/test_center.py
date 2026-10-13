"""brain/api/routes/test_center.py — Smoke, standard, full test suites and results heatmap.
"""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Query
from brain.api.models import TestRunRequest, TestRunStatus
from brain.api.services.test_center_service import start_test_run, get_test_run_status

router = APIRouter(prefix="/test-center", tags=["Test Center"])


@router.post("/run", response_model=TestRunStatus)
def run_tests_endpoint(req: TestRunRequest):
    return start_test_run(req.suite)


@router.get("/status", response_model=TestRunStatus)
def get_test_status_endpoint(run_id: Optional[str] = Query(None)):
    return get_test_run_status(run_id or "")
