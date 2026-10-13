"""brain/api/routes/doctor.py — Comprehensive diagnostic suite and 1-click auto-fixes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
import sqlite3

from brain.api.dependencies import get_db
from brain.api.models import DoctorReport, DoctorFixRequest, DoctorFixResponse
from brain.api.services.doctor_service import run_doctor_checks, execute_doctor_fix

router = APIRouter(prefix="/doctor", tags=["Doctor"])


@router.get("", response_model=DoctorReport)
def get_doctor_report_endpoint(conn: sqlite3.Connection = Depends(get_db)):
    return run_doctor_checks(conn)


@router.post("/fix", response_model=DoctorFixResponse)
def fix_doctor_check_endpoint(req: DoctorFixRequest, conn: sqlite3.Connection = Depends(get_db)):
    return execute_doctor_fix(req.check_id, conn)
