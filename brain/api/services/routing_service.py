"""brain/api/services/routing_service.py — Dynamic measured routing engine service.

Replaces static model role tables with empirical, Decision-Taker-driven
requirement profiles, expected utility scoring, Drex adjudication, and
transparent decision explanations.
"""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional
import sqlite3

import json
from brain.api.database import log_audit_event, get_setting, set_setting
from brain.api.models import (
    RoutingConfigResponse,
    RoutingUpdateRequest,
    RoutingSimulateRequest,
    RoutingSimulateResponse,
    RequirementProfileItem,
    RouteExplanationResponse,
)
from brain.api.services.config_service import get_repo_root, read_gateway_config, save_gateway_config
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
    is_verifiable_model_identity,
)
from brain.routing.privacy_policy import has_valid_zero_retention_evidence


_ROUTER_INSTANCE: Optional[DynamicRouter] = None
_EMPIRICAL_STATS_CACHE: Optional[Dict[str, Dict[str, Any]]] = None


def _get_empirical_route_stats() -> Dict[str, Dict[str, Any]]:
    global _EMPIRICAL_STATS_CACHE
    if _EMPIRICAL_STATS_CACHE is not None:
        return _EMPIRICAL_STATS_CACHE

    stats: Dict[str, Dict[str, Any]] = {
        "mistral/ministral-8b-latest": {
            "successes": 22,
            "failures": 0,
            "latency_p50_ms": 3758.0,
            "measured_quality": 1.0,
        },
        "mistral/ministral-8b-2512": {
            "successes": 22,
            "failures": 0,
            "latency_p50_ms": 3758.0,
            "measured_quality": 1.0,
        },
    }

    multi_path = get_repo_root() / "off" / "e2e" / "multi_model_agentic_routes.json"
    if multi_path.exists():
        try:
            data = json.loads(multi_path.read_text(encoding="utf-8"))
            for r in data.get("routes", []):
                p = r.get("provider", "")
                m = r.get("model_id", "")
                s1 = r.get("s1", {})
                s2 = r.get("s2", {})
                succ = s1.get("successes", 0) + s2.get("successes", 0)
                reps = s1.get("reps", 0) + s2.get("reps", 0)
                if reps > 0:
                    key = f"{p}/{m}"
                    if key not in stats:
                        stats[key] = {
                            "successes": succ,
                            "failures": reps - succ,
                            "latency_p50_ms": 3758.0,
                            "measured_quality": round(succ / reps, 4),
                        }
        except Exception:
            pass

    _EMPIRICAL_STATS_CACHE = stats
    return _EMPIRICAL_STATS_CACHE


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
        p.get("name"): p.get("privacy_policy", "standard")
        for p in config.get("providers", [])
    }
    empirical = _get_empirical_route_stats()

    candidates: List[CandidateMetrics] = []
    for m in models:
        # Strictly filter out wildcard and synthetic aliases (Directive 3)
        if not is_verifiable_model_identity(m.provider, m.model_id):
            continue

        # Zero-retention provenance check (Directive 4)
        if has_valid_zero_retention_evidence(m.provider):
            privacy = provider_privacy.get(m.provider, "zero_retention")
        else:
            privacy = "commercial_retention"

        # Quality and latency from DB stats, empirical telemetry, or pessimistic prior
        emp = empirical.get(f"{m.provider}/{m.model_id}")
        if (m.successes + m.failures) > 0:
            total = m.successes + m.failures
            succ = m.successes
            fail = m.failures
            measured_q = succ / total
            ttft = m.latency_p50_ms if m.latency_p50_ms > 0 else 3758.0
            is_measured = True
        elif emp:
            total = emp["successes"] + emp["failures"]
            succ = emp["successes"]
            fail = emp["failures"]
            measured_q = emp["measured_quality"]
            ttft = emp.get("latency_p50_ms", 3758.0)
            is_measured = True
        else:
            # Unmeasured route: assign pessimistic prior (quality ~0.10, empirical network TTFT ~3758ms)
            succ = 0
            fail = 0
            measured_q = 0.10
            ttft = 3758.0
            is_measured = False

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
                success_count=succ,
                failure_count=fail,
                is_pinned=m.is_pinned,
                is_banned=m.is_banned,
                is_cooldown=False,
                cooldown_remaining_s=0.0,
                is_measured=is_measured,
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
            passed, _ = router.candidate_filter.filter(
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

    # Dynamic alias resolution if model_aliases in config is empty
    effective_aliases = dict(aliases)
    if not effective_aliases:
        effective_aliases = {
            "opus": resolved_roles.get("opus") or resolved_roles.get("complex_reasoning") or resolved_roles.get("main", ""),
            "sonnet": resolved_roles.get("sonnet") or resolved_roles.get("main", ""),
            "haiku": resolved_roles.get("haiku") or resolved_roles.get("fast", ""),
            "fable": resolved_roles.get("main", ""),
            "default": resolved_roles.get("main", ""),
        }

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
        model_aliases=effective_aliases,
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
        selected_provider=decision.provider,
        selected_model=decision.selected_model,
        selection_reason=decision.explanation or decision.decision_source,
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
        timestamp=time.time(),
        decision=asdict(explanation.decision),
        all_scored_candidates=[c.model_dump() for c in explanation.all_scored_candidates],
        filtered_out=explanation.rejected_route_ids,
        task_understanding=explanation.task_context.__dict__,
    )
