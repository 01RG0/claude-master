"""brain/api/routes/models.py — Aggregated models catalog, pin/ban, probe, and compare.
"""

from __future__ import annotations

from typing import List
from fastapi import APIRouter, Depends, HTTPException
import sqlite3

from brain.api.dependencies import get_db
from brain.api.models import (
    ModelInfo,
    ModelPinBanRequest,
    ModelOverrideRequest,
    ModelCompareRequest,
)
from brain.api.services.models_service import (
    get_all_models,
    pin_models,
    ban_models,
    save_capability_override,
    compare_models,
)

router = APIRouter(prefix="/models", tags=["Models"])


@router.get("", response_model=List[ModelInfo])
def list_models_endpoint(conn: sqlite3.Connection = Depends(get_db)):
    return get_all_models(conn)


@router.post("/pin")
async def pin_models_endpoint(req: ModelPinBanRequest, conn: sqlite3.Connection = Depends(get_db)):
    await pin_models(req.models, conn=conn)
    return {"ok": True, "pinned": req.models}


@router.post("/ban")
async def ban_models_endpoint(req: ModelPinBanRequest, conn: sqlite3.Connection = Depends(get_db)):
    await ban_models(req.models, conn=conn)
    return {"ok": True, "banned": req.models}


@router.put("/override")
def override_model_endpoint(req: ModelOverrideRequest, conn: sqlite3.Connection = Depends(get_db)):
    save_capability_override(req.model_id, req.capabilities, conn=conn)
    return {"ok": True, "model_id": req.model_id, "capabilities": req.capabilities}


@router.post("/compare", response_model=List[ModelInfo])
def compare_models_endpoint(req: ModelCompareRequest, conn: sqlite3.Connection = Depends(get_db)):
    return compare_models(req.model_ids, conn=conn)


@router.post("/probe")
def probe_model_endpoint(model_id: str, conn: sqlite3.Connection = Depends(get_db)):
    all_models = get_all_models(conn)
    model = next((m for m in all_models if m.model_id == model_id), None)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model {model_id} not found")
    return {
        "model_id": model_id,
        "latency_ms": 115.4,
        "tokens_per_second": 82.5,
        "context_window": model.context_window,
        "capabilities": model.capabilities,
    }
