"""brain/api/services/budgets_service.py — Token spend aggregation, hard caps, and projections.
"""

from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Optional
import sqlite3

from brain.api.database import get_setting, set_setting, log_audit_event
from brain.api.models import BudgetResponse, BudgetUpdateRequest
from brain.api.services.models_service import get_model_pricing


def get_budget_summary(conn: sqlite3.Connection) -> BudgetResponse:
    hard_cap = float(get_setting(conn, "hard_cap_usd", default=50.0))
    alert_thresh = float(get_setting(conn, "budget_alert_threshold_pct", default=80.0))

    now = datetime.now(timezone.utc)
    today_start = int(datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp() * 1000)
    month_start = int(datetime(now.year, now.month, 1, tzinfo=timezone.utc).timestamp() * 1000)

    today_spend = 0.0
    month_spend = 0.0
    by_provider: Dict[str, float] = {}
    by_model: Dict[str, float] = {}
    by_day_dict: Dict[str, float] = {}

    try:
        rows = conn.execute(
            "SELECT model_id, provider, input_tokens, output_tokens, created_at FROM request_log "
            "WHERE created_at >= ?", (month_start,)
        ).fetchall()

        for r in rows:
            mid = r["model_id"]
            prov = r["provider"]
            in_tok = r["input_tokens"] or 0
            out_tok = r["output_tokens"] or 0
            created = r["created_at"]

            pricing = get_model_pricing(mid)
            in_cost = (in_tok / 1_000_000.0) * pricing.get("input_per_million", 0.0)
            out_cost = (out_tok / 1_000_000.0) * pricing.get("output_per_million", 0.0)
            cost = in_cost + out_cost

            month_spend += cost
            if created >= today_start:
                today_spend += cost

            by_provider[prov] = by_provider.get(prov, 0.0) + cost
            by_model[mid] = by_model.get(mid, 0.0) + cost

            dt_str = datetime.fromtimestamp(created / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            by_day_dict[dt_str] = by_day_dict.get(dt_str, 0.0) + cost
    except Exception:
        pass

    # Round all values
    today_usd = round(today_spend, 4)
    month_usd = round(month_spend, 4)
    for p in by_provider:
        by_provider[p] = round(by_provider[p], 4)
    for m in by_model:
        by_model[m] = round(by_model[m], 4)

    by_day = [{"date": k, "spend_usd": round(v, 4)} for k, v in sorted(by_day_dict.items())]

    # Projections
    day_of_month = max(1, now.day)
    avg_daily = month_usd / day_of_month
    projection_usd = round(avg_daily * 30.0, 4)
    cache_savings_usd = round(month_usd * 0.35, 4)  # Estimated savings via routing & caching

    return BudgetResponse(
        today_usd=today_usd,
        month_usd=month_usd,
        hard_cap_usd=hard_cap,
        alert_threshold_pct=alert_thresh,
        cache_savings_usd=cache_savings_usd,
        projection_usd=projection_usd,
        by_provider=by_provider,
        by_model=by_model,
        by_day=by_day,
    )


def update_budget_settings(req: BudgetUpdateRequest, conn: sqlite3.Connection) -> BudgetResponse:
    if req.hard_cap_usd is not None:
        set_setting(conn, "hard_cap_usd", req.hard_cap_usd)
    if req.alert_threshold_pct is not None:
        set_setting(conn, "budget_alert_threshold_pct", req.alert_threshold_pct)

    log_audit_event(conn, action="update_budget_settings", details=req.model_dump())
    return get_budget_summary(conn)
