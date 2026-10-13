"""brain/api/routes/routing.py — Role mappings, strategy, requirement profiles, simulation, and explanations.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
import sqlite3

from brain.api.dependencies import get_db
from brain.api.models import (
    RoutingConfigResponse,
    RoutingUpdateRequest,
    RoutingSimulateRequest,
    RoutingSimulateResponse,
    RequirementProfileItem,
    RouteExplanationResponse,
)
from brain.api.services.routing_service import (
    get_routing_config,
    update_routing_config,
    simulate_routing,
    get_requirement_profiles,
    get_requirement_profile_by_name,
    save_requirement_profile_item,
    explain_routing_decision,
)

router = APIRouter(prefix="/routing", tags=["Routing"])


@router.get("", response_model=RoutingConfigResponse)
def get_routing_endpoint(conn: sqlite3.Connection = Depends(get_db)):
    return get_routing_config(conn)


@router.put("", response_model=RoutingConfigResponse)
def update_routing_endpoint(req: RoutingUpdateRequest, conn: sqlite3.Connection = Depends(get_db)):
    return update_routing_config(req, conn=conn)


@router.post("/simulate", response_model=RoutingSimulateResponse)
def simulate_routing_endpoint(req: RoutingSimulateRequest, conn: sqlite3.Connection = Depends(get_db)):
    return simulate_routing(req, conn=conn)


@router.get("/profiles", response_model=List[RequirementProfileItem])
def list_profiles_endpoint():
    return get_requirement_profiles()


@router.get("/profiles/{name}", response_model=RequirementProfileItem)
def get_profile_endpoint(name: str):
    return get_requirement_profile_by_name(name)


@router.put("/profiles/{name}", response_model=RequirementProfileItem)
def update_profile_endpoint(name: str, item: RequirementProfileItem):
    item.name = name
    return save_requirement_profile_item(item)


@router.get("/explain/{request_id}")
def explain_routing_endpoint(request_id: str, conn: sqlite3.Connection = Depends(get_db)):
    # 1. Check DynamicRouter explanation first
    exp = explain_routing_decision(request_id)
    if exp:
        return exp.model_dump()

    # 2. Check LearningRouter explanation
    try:
        from brain.routing.learning import get_learning_router
        lr = get_learning_router(conn)
        res = lr.explain(request_id)
        if res and not res.get("error"):
            return res
    except Exception:
        pass

    if exp:
        return exp.model_dump()

    raise HTTPException(status_code=404, detail=f"No routing explanation found for request '{request_id}'")
