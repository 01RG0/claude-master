"""brain/api/services/routing_service.py — Dynamic measured routing engine service.

Replaces static model role tables with empirical, Decision-Taker-driven
requirement profiles, expected utility scoring, Drex adjudication, and
transparent decision explanations.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
import sqlite3

from brain.api.database import log_audit_event, get_setting, set_setting
from brain.api.models import (
    RoutingConfigResponse,
    RoutingUpdateRequest,
    RoutingSimulateRequest,
    RoutingSimulateResponse,
    RequirementProfileItem,
    RouteExplanationResponse,
)
from brain.api.services.config_service import read_gateway_config, save_gateway_config
from brain.api.services.models_service import get_all_models, get_model_pricing
from brain.routing.profiles import (
    load_profiles,
    save_profiles,
    get_profile,
    RequirementProfile,
    HardConstraints,
    SoftObjectives,
)
from brain.routing.scorer import CandidateMetrics, ScoredCandidate
from brain.routing.engine import (
    DynamicRouter,
    RouteRequest,
    RouteDecision,
    RouteExplanation,
)


_ROUTER_INSTANCE: Optional[DynamicRouter] = None


def get_dynamic_router() -> DynamicRouter:
    global _ROUTER_INSTANCE
    if _ROUTER_INSTANCE is None:
        _ROUTER_INSTANCE = DynamicRouter()
    return _ROUTER_INSTANCE


def build_candidate_metrics_from_models(conn: Optional[sqlite3.Connection] = None) -> List[CandidateMetrics]:
    """Dynamically converts active catalog models into route candidates."""
    models = get_all_models(conn)
    config = read_gateway_config()
    provider_privacy = {
        p.get("name"): p.get("privacy_policy", "zero_retention")
        for p in config.get("providers", [])
    }

    candidates: List[CandidateMetrics] = []
    for m in models:
        privacy = provider_privacy.get(m.provider, "zero_retention")
        # Quality estimate from success rate or baseline
        total = m.successes + m.failures
        measured_q = (m.successes / total) if total > 0 else 0.75
        ttft = m.latency_p50_ms if m.latency_p50_ms > 0 else 350.0

        candidates.append(
            CandidateMetrics(
                model_id=m.model_id,
                provider=m.provider,
                route_id=f"{m.provider}/{m.model_id}",
                context_window=m.context_window,
                pricing=m.pricing,
                capabilities=m.capabilities,
                privacy_policy=privacy,
                measured_quality=measured_q,
                measured_ttft_ms=ttft,
                success_count=m.successes,
                failure_count=m.failures,
                is_pinned=m.is_pinned,
                is_banned=m.is_banned,
                is_cooldown=False,
                cooldown_remaining_s=0.0,
            )
        )
    return candidates


def get_routing_config(conn: Optional[sqlite3.Connection] = None) -> RoutingConfigResponse:
    config = read_gateway_config()
    routing = config.get("routing", {})
    aliases = config.get("model_aliases", {})
    rules = get_setting(conn, "routing_rules", default=[]) if conn else []

    profiles = load_profiles()
    candidates = build_candidate_metrics_from_models(conn)
    router = get_dynamic_router()

    # Dynamically resolve roles and fallback chains per requirement profile
    resolved_roles: Dict[str, str] = {}
    resolved_fallbacks: Dict[str, List[str]] = {}

    # Check if user defined manual role overrides in config
    manual_roles = config.get("roles", {})

    for p_name, profile in profiles.items():
        if p_name in manual_roles and manual_roles[p_name]:
            resolved_roles[p_name] = manual_roles[p_name]
            resolved_fallbacks[p_name] = [c.model_id for c in candidates if c.model_id != manual_roles[p_name]][:3]
        elif candidates:
            # Dynamically score candidates against this requirement profile
            passed, _ = router.filter_engine.filter(
                candidates,
                profile,
                router.classifier.classify("", prompt_tokens=500),
            )
            pool = passed if passed else [c for c in candidates if not c.is_banned]
            if pool:
                scored = router.scorer.score_all(pool, profile=profile, prompt_tokens=500)
                if scored:
                    resolved_roles[p_name] = scored[0].metrics.model_id
                    resolved_fallbacks[p_name] = [s.metrics.model_id for s in scored[1:4]]
                else:
                    resolved_roles[p_name] = pool[0].model_id
                    resolved_fallbacks[p_name] = [c.model_id for c in pool[1:4]]
            else:
                resolved_roles[p_name] = candidates[0].model_id
                resolved_fallbacks[p_name] = []
        else:
            resolved_roles[p_name] = ""
            resolved_fallbacks[p_name] = []

    profiles_dump = {
        name: {
            "description": p.description,
            "hard_constraints": p.hard_constraints.model_dump(),
            "soft_objectives": p.soft_objectives.model_dump(),
        }
        for name, p in profiles.items()
    }

    return RoutingConfigResponse(
        strategy=routing.get("strategy", "dynamic_expected_utility"),
        cooldown_base_s=routing.get("cooldown_base_s", 60),
        cooldown_max_s=routing.get("cooldown_max_s", 3600),
        roles=resolved_roles,
        model_aliases=aliases,
        fallback_chains=resolved_fallbacks,
        rules=rules,
        profiles=profiles_dump,
    )


def update_routing_config(req: RoutingUpdateRequest, conn: Optional[sqlite3.Connection] = None) -> RoutingConfigResponse:
    config = read_gateway_config()
    routing = config.setdefault("routing", {})

    if req.strategy is not None:
        routing["strategy"] = req.strategy
    if req.cooldown_base_s is not None:
        routing["cooldown_base_s"] = req.cooldown_base_s
    if req.cooldown_max_s is not None:
        routing["cooldown_max_s"] = req.cooldown_max_s

    if req.roles is not None:
        config["roles"] = req.roles
    if req.model_aliases is not None:
        config["model_aliases"] = req.model_aliases

    if req.fallback_chains is not None and conn:
        set_setting(conn, "routing_fallback_chains", req.fallback_chains)
    if req.rules is not None and conn:
        set_setting(conn, "routing_rules", req.rules)

    save_gateway_config(config, conn=conn, audit_action="update_routing_config")
    return get_routing_config(conn)


def simulate_routing(req: RoutingSimulateRequest, conn: Optional[sqlite3.Connection] = None) -> RoutingSimulateResponse:
    candidates = build_candidate_metrics_from_models(conn)
    router = get_dynamic_router()

    route_req = RouteRequest(
        prompt=req.task,
        profile_name=req.role,
        prompt_tokens=req.prompt_tokens,
        images=[{"type": "image"}] if req.requires_vision else None,
        session_id=req.session_id,
        is_tool_loop=req.is_tool_loop,
        force_explore=req.force_explore,
        custom_candidates=candidates if candidates else None,
    )

    decision = router.route(route_req)

    return RoutingSimulateResponse(
        resolved_role=decision.resolved_profile,
        selected_provider=decision.selected_provider,
        selected_model=decision.selected_model,
        selection_reason=decision.reason,
        estimated_cost_usd=decision.estimated_cost_usd,
        fallback_chain=decision.fallback_chain,
        request_id=decision.request_id,
        decision_source=decision.decision_source,
        confidence=decision.confidence,
    )


def get_requirement_profiles() -> List[RequirementProfileItem]:
    profiles = load_profiles()
    return [
        RequirementProfileItem(
            name=name,
            description=p.description,
            hard_constraints=p.hard_constraints.model_dump(),
            soft_objectives=p.soft_objectives.model_dump(),
        )
        for name, p in profiles.items()
    ]


def get_requirement_profile_by_name(name: str) -> RequirementProfileItem:
    profile = get_profile(name)
    return RequirementProfileItem(
        name=profile.name,
        description=profile.description,
        hard_constraints=profile.hard_constraints.model_dump(),
        soft_objectives=profile.soft_objectives.model_dump(),
    )


def save_requirement_profile_item(item: RequirementProfileItem) -> RequirementProfileItem:
    profiles = load_profiles()
    profile = RequirementProfile(
        name=item.name,
        description=item.description,
        hard_constraints=HardConstraints(**item.hard_constraints),
        soft_objectives=SoftObjectives(**item.soft_objectives).normalized(),
    )
    profiles[item.name] = profile
    save_profiles(profiles)
    return item


def explain_routing_decision(request_id: str) -> Optional[RouteExplanationResponse]:
    router = get_dynamic_router()
    explanation = router.explain(request_id)
    if not explanation:
        return None

    return RouteExplanationResponse(
        request_id=explanation.request_id,
        timestamp=explanation.timestamp,
        decision=explanation.decision.model_dump(),
        all_scored_candidates=[c.model_dump() for c in explanation.all_scored_candidates],
        filtered_out=explanation.filtered_out,
        task_understanding=explanation.task_understanding.model_dump(),
    )
