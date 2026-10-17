"""Dynamic Routing Engine with Cold-Start and Multi-Route Resolution.

Integrates requirement profiling, candidate filtering, Bayesian expected utility,
cold-start prior injection, and bandit exploration.

Exports:
    DynamicRouter           – full pipeline (classify → filter → score → drex → escalate)
    DynamicRoutingEngine    – alias retained for backwards compatibility
    TaskClassifier          – deterministic task-type / language / complexity classifier
    CandidateFilter         – hard-constraint gate on CandidateMetrics
    RouteRequest            – input dataclass for DynamicRouter.route()
    RouteDecision           – output dataclass from DynamicRouter.route()
    TaskContext             – result of TaskClassifier.classify()
    RouteExplanation        – full trace for DynamicRouter.explain()
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from brain.routing.catalog import CanonicalModel, Route
from brain.routing.scorer import (
    CandidateMetrics,
    ScoredCandidate,
    ExpectedUtilityScorer,
    ModelScorer,
    QualityScore,
)
from brain.routing.profiles import RequirementProfile, HardConstraints, SoftObjectives
from brain.routing.bandit import BanditRouter
from brain.routing.drex_router import DrexRouter, DrexRoutingResult
from brain.routing.escalation import EscalationManager, FailureType
from brain.routing.hyperparameters import get_hyperparameter
from brain.routing.privacy_policy import has_valid_zero_retention_evidence

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Dataclasses
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TaskContext:
    """Result of classifying a request prompt."""
    task_type: str = "general"          # code_generation, planning, summarization, visual_analysis, general
    language: str = "en"               # en, ar, code, …
    complexity: str = "medium"         # low, medium, high
    vision_needed: bool = False
    tools_needed: bool = True
    prompt_tokens: int = 0             # estimated
    multi_step: bool = False


@dataclass
class RouteRequest:
    """Input to DynamicRouter.route()."""
    prompt: str
    profile_name: str = "main"
    images: List[Any] = field(default_factory=list)
    prompt_tokens: int = 0
    session_id: Optional[str] = None
    is_tool_loop: bool = False
    request_id: Optional[str] = None
    force_explore: bool = False                          # force bandit exploration on this request
    custom_candidates: Optional[List[Any]] = None       # override the router's internal pool
    require_zero_retention: bool = False
    privacy_policy: Optional[str] = None

    def __post_init__(self):
        if self.request_id is None:
            self.request_id = str(uuid.uuid4())



@dataclass
class RouteDecision:
    """Output of DynamicRouter.route()."""
    request_id: str
    selected_route_id: str
    selected_model: str
    provider: str
    resolved_profile: str
    task_context: TaskContext
    decision_source: str          # deterministic | drex | drex_fallback | cache_retention | escalation
    composite_utility: float
    fallback_chain: List[str]     # ordered route_ids available as fallback
    handoff_occurred: bool = False
    # Legacy / compat fields used by DynamicRoutingEngine
    canonical_id: str = ""
    provider_model_id: str = ""
    expected_quality: float = 0.0
    exploration_bonus: float = 0.0
    is_cold_start: bool = False
    pricing: Dict[str, float] = field(default_factory=dict)
    measured_latency_ms: float = 0.0
    estimated_cost_usd: float = 0.0
    confidence: float = 0.0
    explanation: str = ""


@dataclass
class RouteExplanation:
    """Full decision trace for /api/routing/explain/<id>."""
    request_id: str
    decision: RouteDecision
    task_context: TaskContext
    all_scored_candidates: List[ScoredCandidate]
    rejected_route_ids: Dict[str, str]  # route_id → rejection reason
    drex_result: Optional[DrexRoutingResult] = None
    wall_time_ms: float = 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Task Classifier
# ──────────────────────────────────────────────────────────────────────────────

class TaskClassifier:
    """Deterministic pattern-based task classifier. No model calls."""

    _ARABIC_RE = re.compile(r'[\u0600-\u06FF]')
    _CODE_RE = re.compile(r'(def |class |import |#include|function |const |let |var |{|}|\bsql\b)', re.I)
    _VISION_RE = re.compile(r'\b(screenshot|diagram|image|png|jpg|jpeg|figure|chart|wireframe|photo)\b', re.I)
    _PLAN_RE = re.compile(r'\b(roadmap|architecture|migration|adr|plan|design|strategy|step\s+\d|phase\s+\d)\b', re.I)
    _SUMM_RE = re.compile(r'\b(summarize|summary|tldr|tl;dr|recap|condense|brief)\b', re.I)
    _MULTI_RE = re.compile(r'\b(then|next|step\s+\d|after that|finally|first)\b', re.I)

    def classify(self, prompt: str, prompt_tokens: int = 0) -> TaskContext:
        text = prompt.strip()
        vision_needed = bool(self._VISION_RE.search(text))
        language = "ar" if self._ARABIC_RE.search(text) else ("code" if self._CODE_RE.search(text) else "en")

        if vision_needed:
            task_type = "visual_analysis"
        elif self._SUMM_RE.search(text):
            task_type = "summarization"
        elif self._PLAN_RE.search(text):
            task_type = "planning"
        elif self._CODE_RE.search(text):
            task_type = "code_generation"
        else:
            task_type = "general"

        # Complexity heuristic
        if len(text) > 2000 or bool(self._MULTI_RE.search(text)):
            complexity = "high"
        elif len(text) > 400:
            complexity = "medium"
        else:
            complexity = "low"

        multi_step = bool(self._MULTI_RE.search(text))
        if prompt_tokens <= 0:
            prompt_tokens = len(text) // 4

        return TaskContext(
            task_type=task_type,
            language=language,
            complexity=complexity,
            vision_needed=vision_needed,
            tools_needed=True,
            prompt_tokens=prompt_tokens,
            multi_step=multi_step,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Candidate Filter
# ──────────────────────────────────────────────────────────────────────────────

def is_verifiable_model_identity(provider: str, model_id: str) -> bool:
    """Strictly filter out wildcard and synthetic aliases like aihubmix/auto, pooled/*, *."""
    if not model_id or not provider:
        return False
    p = str(provider).lower().strip()
    m = str(model_id).lower().strip()
    if p in ("pooled", "aihorde", "pollinations") or p.startswith("pooled"):
        return False
    if m == "*" or "*" in m or m.startswith("*/") or m.endswith("/*"):
        return False
    if m == "auto" or m.startswith("auto/") or m.endswith("/auto") or "/auto" in m or "auto/" in m:
        return False
    if m in ("default", "none", "unknown"):
        return False
    return True


class CandidateFilter:
    """Applies hard constraints from a RequirementProfile against CandidateMetrics."""

    def filter(
        self,
        candidates: List[CandidateMetrics],
        profile: RequirementProfile,
        task: TaskContext,
    ) -> Tuple[List[CandidateMetrics], Dict[str, str]]:
        """
        Returns (passed, rejections) where rejections maps route_id → reason.
        """
        passed: List[CandidateMetrics] = []
        rejections: Dict[str, str] = {}
        hc = profile.hard_constraints

        for c in candidates:
            # Directive 3: strictly filter out wildcard and synthetic aliases
            if not is_verifiable_model_identity(c.provider, c.model_id):
                rejections[c.route_id] = "unverifiable_alias"
                continue
            if c.is_banned:
                rejections[c.route_id] = "banned"
                continue
            if c.is_cooldown:
                rejections[c.route_id] = f"cooldown:{c.cooldown_remaining_s:.0f}s"
                continue
            if hc.tool_calling and not c.capabilities.get("tools", False):
                rejections[c.route_id] = "no_tool_calling"
                continue
            if (task.vision_needed or hc.vision) and not c.capabilities.get("vision", False):
                rejections[c.route_id] = "no_vision"
                continue
            if c.context_window < hc.min_context:
                rejections[c.route_id] = f"context_too_small:{c.context_window}<{hc.min_context}"
                continue
            # Directive 6: Strict zero-retention policy and provenance enforcement
            if hc.privacy == "zero_retention" or getattr(hc, "require_zero_retention", False):
                if c.privacy_policy != "zero_retention":
                    rejections[c.route_id] = f"privacy_mismatch:{c.privacy_policy}"
                    continue
                if not has_valid_zero_retention_evidence(c.provider):
                    rejections[c.route_id] = f"zero_retention_unverified:{c.provider}"
                    continue
            elif hc.privacy and c.privacy_policy not in (hc.privacy, "zero_retention"):
                rejections[c.route_id] = f"privacy_mismatch:{c.privacy_policy}"
                continue
            passed.append(c)

        return passed, rejections


# ──────────────────────────────────────────────────────────────────────────────
# Dynamic Router  (the full pipeline)
# ──────────────────────────────────────────────────────────────────────────────

class DynamicRouter:
    """
    Full 7-stage routing pipeline:
      1. Classify task
      2. Load requirement profile
      3. Hard-constraint filter
      4. Score remaining candidates (ExpectedUtilityScorer)
      5. Drex consultation on borderline decisions
      6. Session / tool-loop cache retention
      7. Bandit exploration budget
    """

    def __init__(
        self,
        scorer: Optional[ExpectedUtilityScorer] = None,
        bandit: Optional[BanditRouter] = None,
        drex_router: Optional[DrexRouter] = None,
        escalation_manager: Optional[EscalationManager] = None,
    ):
        self.classifier = TaskClassifier()
        self.candidate_filter = CandidateFilter()
        self.filter_engine = self.candidate_filter
        self.scorer = scorer or ExpectedUtilityScorer()
        self.bandit = bandit or BanditRouter()
        self.drex = drex_router or DrexRouter()
        self.escalation = escalation_manager or EscalationManager()

        # In-memory pools and traces
        self._candidates: List[CandidateMetrics] = []
        self._session_models: Dict[str, str] = {}   # session_id → model_id
        self._traces: Dict[str, RouteExplanation] = {}

    # ── public API ──────────────────────────────────────────────────────────

    def set_candidate_pool(self, candidates: List[CandidateMetrics]) -> None:
        """Replace the active candidate pool (used by tests and service layer)."""
        self._candidates = candidates

    def route(self, req: RouteRequest) -> RouteDecision:
        """Run the full routing pipeline for a request. Returns RouteDecision."""
        t0 = time.monotonic()

        # ── Stage 1: classify ──────────────────────────────────────────────
        task = self.classifier.classify(req.prompt)
        if req.images:
            task.vision_needed = True
        if req.prompt_tokens:
            task.prompt_tokens = req.prompt_tokens

        # ── Stage 6: session / tool-loop cache retention ───────────────────
        if req.session_id and req.is_tool_loop:
            sticky = self._session_models.get(req.session_id)
            if sticky:
                # Keep same model for cache coherence
                matching = [c for c in self._candidates if c.model_id == sticky]
                if matching:
                    c = matching[0]
                    dec = self._make_decision(
                        req=req,
                        candidate=c,
                        scored=[],
                        task=task,
                        source="cache_retention",
                        profile_name=req.profile_name,
                        rejections={},
                        all_scored=[],
                    )
                    self._record_trace(req, dec, task, [], {}, None, t0)
                    return dec

        # ── Stage 2: load profile ──────────────────────────────────────────
        try:
            from brain.routing.profiles import get_profile
            profile = get_profile(req.profile_name)
        except Exception:
            profile = RequirementProfile(name=req.profile_name)

        if req.require_zero_retention or req.privacy_policy == "zero_retention":
            profile.hard_constraints.require_zero_retention = True
            profile.hard_constraints.privacy = "zero_retention"

        # ── Stage 3: hard-constraint filter ───────────────────────────────
        pool = req.custom_candidates if req.custom_candidates is not None else (self._candidates or [])
        passed, rejections = self.candidate_filter.filter(pool, profile, task)

        if not passed:
            # If zero retention is strictly mandated, do not fall back to non-compliant candidates
            if not (profile.hard_constraints.privacy == "zero_retention" or profile.hard_constraints.require_zero_retention):
                # Emergency fallback: use any non-banned candidate
                passed = [c for c in pool if not c.is_banned]
                if not passed:
                    passed = pool  # last resort

        # ── Stage 4: score candidates ──────────────────────────────────────
        session_active = self._session_models.get(req.session_id or "") if req.session_id else None
        all_scored = self.scorer.score_all(passed, profile, session_active_model=session_active)

        if not all_scored:
            # Nothing scored → return first available
            fallback_c = pool[0] if pool else CandidateMetrics(
                model_id="fallback", provider="none", route_id="none/fallback"
            )
            dec = self._make_decision(req, fallback_c, [], task, "no_candidates", req.profile_name, rejections, [])
            self._record_trace(req, dec, task, [], rejections, None, t0)
            return dec

        # Sort descending by utility
        all_scored.sort(key=lambda s: s.utility_score, reverse=True)

        measured_scored = [s for s in all_scored if s.metrics.measured]
        unmeasured_scored = [s for s in all_scored if not s.metrics.measured]

        # Directive 3 Cold-start exploration gate:
        # Unmeasured routes can ONLY be selected via capped exploration budget (force_explore or bandit bonus).
        # In deterministic routing and Drex adjudication, only measured routes are evaluated when available.
        eval_pool = measured_scored if (measured_scored and not req.force_explore) else all_scored

        # ── Stage 5: Drex consultation ─────────────────────────────────────
        drex_result: Optional[DrexRoutingResult] = None
        try:
            drex_result = self.drex.decide(eval_pool, task_summary=req.prompt[:200])
            best_scored = drex_result.selected
            source = drex_result.source
        except Exception:
            best_scored = eval_pool[0]
            source = "deterministic"

        # ── Stage 7: bandit exploration ────────────────────────────────────
        undersampled = self.bandit.get_undersampled_candidates(passed)
        if req.force_explore:
            if unmeasured_scored:
                best_scored = unmeasured_scored[0]
                source = "exploration_forced"
            elif undersampled:
                best_scored = self.scorer.score_all([undersampled[0]], profile)[0] or best_scored
                source = "exploration_forced"
        elif undersampled and self.bandit.should_explore(undersampled):
            # Capped bandit exploration bonus
            explore_cand = unmeasured_scored[0] if unmeasured_scored else self.scorer.score_all([undersampled[0]], profile)[0]
            if explore_cand:
                best_scored = explore_cand
                source = "exploration"

        # ── Record session model ───────────────────────────────────────────
        if req.session_id:
            self._session_models[req.session_id] = best_scored.metrics.model_id

        # ── Build decision ─────────────────────────────────────────────────
        fallback_chain = [s.metrics.route_id for s in all_scored[1:6]]
        dec = self._make_decision(req, best_scored.metrics, [best_scored], task, source,
                                  req.profile_name, rejections, all_scored)
        dec.fallback_chain = fallback_chain
        dec.composite_utility = round(best_scored.utility_score, 4)
        dec.explanation = best_scored.explanation

        self._record_trace(req, dec, task, all_scored, rejections, drex_result, t0)
        return dec

    def escalate(
        self,
        session_id: str,
        failed_route_id: str,
        failure_type: FailureType,
        request: RouteRequest,
    ) -> RouteDecision:
        """Escalate a failed route to the next best candidate."""
        task = self.classifier.classify(request.prompt)
        try:
            from brain.routing.profiles import get_profile
            profile = get_profile(request.profile_name)
        except Exception:
            profile = RequirementProfile(name=request.profile_name)

        passed, rejections = self.candidate_filter.filter(self._candidates, profile, task)
        all_scored = self.scorer.score_all(passed, profile)
        all_scored.sort(key=lambda s: s.utility_score, reverse=True)

        escalated = self.escalation.select_escalation_candidate(
            session_id=session_id,
            failed_route_id=failed_route_id,
            failure_type=failure_type,
            available_candidates=all_scored,
        )

        if escalated:
            c = escalated.metrics
        elif all_scored:
            c = all_scored[0].metrics
        else:
            c = CandidateMetrics(model_id="fallback", provider="none", route_id="none/fallback")

        dec = self._make_decision(
            req=request,
            candidate=c,
            scored=all_scored,
            task=task,
            source="escalation",
            profile_name=request.profile_name,
            rejections=rejections,
            all_scored=all_scored,
        )
        dec.handoff_occurred = True
        if request.session_id:
            self._session_models[request.session_id] = c.model_id
        return dec

    def explain(self, request_id: str) -> Optional[RouteExplanation]:
        """Return the full decision trace for a previous request."""
        return self._traces.get(request_id)

    # ── private helpers ──────────────────────────────────────────────────────

    def _make_decision(
        self,
        req: RouteRequest,
        candidate: CandidateMetrics,
        scored: List[ScoredCandidate],
        task: TaskContext,
        source: str,
        profile_name: str,
        rejections: Dict[str, str],
        all_scored: List[ScoredCandidate],
    ) -> RouteDecision:
        utility = scored[0].utility_score if scored else 0.0
        fallback = [s.metrics.route_id for s in all_scored[1:6]]
        return RouteDecision(
            request_id=req.request_id or str(uuid.uuid4()),
            selected_route_id=candidate.route_id,
            selected_model=candidate.model_id,
            provider=candidate.provider,
            resolved_profile=profile_name,
            task_context=task,
            decision_source=source,
            composite_utility=round(utility, 4),
            fallback_chain=fallback,
            handoff_occurred=False,
            # legacy compat
            canonical_id=candidate.model_id,
            provider_model_id=candidate.model_id,
            expected_quality=candidate.measured_quality,
            exploration_bonus=0.0,
            is_cold_start=False,
            pricing=candidate.pricing,
            measured_latency_ms=candidate.measured_ttft_ms,
            estimated_cost_usd=scored[0].estimated_cost_usd if scored else 0.0,
            confidence=scored[0].confidence if scored else 0.0,
            explanation="",
        )

    def _record_trace(
        self,
        req: RouteRequest,
        dec: RouteDecision,
        task: TaskContext,
        all_scored: List[ScoredCandidate],
        rejections: Dict[str, str],
        drex_result: Optional[DrexRoutingResult],
        t0: float,
    ) -> None:
        wall_ms = (time.monotonic() - t0) * 1000
        exp = RouteExplanation(
            request_id=req.request_id or dec.request_id,
            decision=dec,
            task_context=task,
            all_scored_candidates=all_scored,
            rejected_route_ids=rejections,
            drex_result=drex_result,
            wall_time_ms=round(wall_ms, 2),
        )
        self._traces[exp.request_id] = exp


# ──────────────────────────────────────────────────────────────────────────────
# Legacy / catalogue-based engine (retained for catalogue-auditor usage)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class RoutingRequirements:
    min_context: int = 4096
    require_tools: bool = True
    require_vision: bool = False
    max_cost_per_m: Optional[float] = None
    max_latency_ms: Optional[float] = None
    allow_exploration: bool = True
    exploration_budget_usd: float = 5.0
    weight_quality: float = 0.50
    weight_latency: float = 0.25
    weight_cost: float = 0.25


class DynamicRoutingEngine:
    """Catalog-based routing engine (works directly on CanonicalModel / Route objects).
    Retained for catalogue-auditor and import compatibility."""

    def __init__(
        self,
        models: Dict[str, CanonicalModel],
        routes: Dict[str, Route],
        scorer: Optional[ModelScorer] = None,
    ):
        self.models = models
        self.routes = routes
        self.scorer = scorer or ModelScorer()
        self.spent_exploration_usd: float = 0.0

    def filter_candidates(self, req: RoutingRequirements) -> List[CanonicalModel]:
        eligible: List[CanonicalModel] = []
        for model in self.models.values():
            if not model.is_agentic:
                continue
            if model.context_window < req.min_context:
                continue
            if req.require_tools and not model.capabilities.get("tools", False):
                continue
            if req.require_vision and not model.capabilities.get("vision", False):
                continue
            valid_routes = [
                self.routes[r_id] for r_id in model.routes
                if r_id in self.routes and self.routes[r_id].healthy
            ]
            if not valid_routes:
                continue
            eligible.append(model)
        return eligible

    def select_best_route_for_model(self, model: CanonicalModel, req: RoutingRequirements) -> Optional[Route]:
        candidate_routes = [
            self.routes[r_id] for r_id in model.routes
            if r_id in self.routes and self.routes[r_id].healthy
        ]
        if not candidate_routes:
            return None
        if req.max_cost_per_m is not None:
            filtered = [r for r in candidate_routes if r.pricing.get("prompt_per_m", 0.0) <= req.max_cost_per_m]
            if filtered:
                candidate_routes = filtered
        candidate_routes.sort(key=lambda r: (r.priority, r.measured_latency_ms,
                                              r.pricing.get("prompt_per_m", 0.0) + r.pricing.get("completion_per_m", 0.0)))
        return candidate_routes[0]

    def route_request(self, req: RoutingRequirements) -> Optional[RouteDecision]:
        candidates = self.filter_candidates(req)
        if not candidates:
            logger.warning("No eligible candidates found satisfying hard constraints")
            return None
        best_decision: Optional[RouteDecision] = None
        best_utility = -float("inf")
        for model in candidates:
            route = self.select_best_route_for_model(model, req)
            if not route:
                continue
            score = self.scorer.get_or_create_score(
                canonical_id=model.canonical_id,
                vendor=model.vendor,
                family=model.family,
                parameter_size=model.parameter_size,
            )
            norm_lat = min(1.0, route.measured_latency_ms / 2000.0)
            tot_cost = route.pricing.get("prompt_per_m", 0.0) + route.pricing.get("completion_per_m", 0.0)
            norm_cost = min(1.0, tot_cost / 5.0)
            exploration_bonus = 0.0
            if req.allow_exploration and self.spent_exploration_usd < req.exploration_budget_usd:
                exploration_bonus = score.exploration_bonus
            utility = (
                (req.weight_quality * score.mean_quality)
                - (req.weight_latency * norm_lat)
                - (req.weight_cost * norm_cost)
                + exploration_bonus
            )
            explanation = (
                f"Model {model.canonical_id} via {route.provider} | "
                f"Quality={score.mean_quality:.2f} (cold_start={score.is_cold_start}), "
                f"Latency={route.measured_latency_ms:.1f}ms, Cost=${tot_cost:.3f}/1M, "
                f"ExpBonus={exploration_bonus:.3f} -> Utility={utility:.3f}"
            )
            if utility > best_utility:
                best_utility = utility
                best_decision = RouteDecision(
                    request_id=str(uuid.uuid4()),
                    selected_route_id=route.route_id,
                    selected_model=route.provider_model_id,
                    provider=route.provider,
                    resolved_profile="legacy",
                    task_context=TaskContext(),
                    decision_source="deterministic",
                    composite_utility=round(utility, 4),
                    fallback_chain=[],
                    canonical_id=model.canonical_id,
                    provider_model_id=route.provider_model_id,
                    expected_quality=score.mean_quality,
                    exploration_bonus=exploration_bonus,
                    is_cold_start=score.is_cold_start,
                    pricing=route.pricing,
                    measured_latency_ms=route.measured_latency_ms,
                    explanation=explanation,
                )
        return best_decision
