"""brain/api/routes/budgets.py — Spend tracking, budget caps, and projections.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
import sqlite3

from brain.api.dependencies import get_db
from brain.api.models import BudgetResponse, BudgetUpdateRequest
from brain.api.services.budgets_service import get_budget_summary, update_budget_settings

router = APIRouter(prefix="/budgets", tags=["Budgets"])


@router.get("", response_model=BudgetResponse)
def get_budgets_endpoint(conn: sqlite3.Connection = Depends(get_db)):
    return get_budget_summary(conn)


@router.put("", response_model=BudgetResponse)
def update_budgets_endpoint(req: BudgetUpdateRequest, conn: sqlite3.Connection = Depends(get_db)):
    return update_budget_settings(req, conn)
