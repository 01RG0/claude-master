"""tests/routing/test_dynamic_router.py — Comprehensive tests for the Dynamic Routing Engine.

Verifies:
1. Requirement Profiles (hard constraints, soft objective normalization, loading/saving).
2. Task Understanding deterministic classifier (types, complexity, language, tools/vision).
3. Candidate Filtering (tools, vision, context window, privacy, circuit breaker, bans).
4. Expected Utility Scorer (Bayesian quality, TTFT, cost, reliability, cache affinity, CI).
5. Bandit Exploration (budget caps, under-sampled routes).
6. Decision Taker Drex adjudication (borderline triggers, thresholding, fallbacks).
7. Escalation & State Preservation (failure types, strictly stronger escalation).
8. Session & Tool-loop consistency (cache retention, safe handoff).
9. Explainability & Trace generation.

CRITICAL INVARIANT: Zero vendor model names hardcoded in code or test definitions.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from brain.routing.profiles import (
    HardConstraints,
    SoftObjectives,
    RequirementProfile,
    load_profiles,
    save_profiles,
    get_profile,
    list_profiles,
)
from brain.routing.scorer import (
    CandidateMetrics,
    ScoredCandidate,
    ExpectedUtilityScorer,
)
from brain.routing.bandit import BanditRouter, BanditState
from brain.routing.drex_router import DrexRouter, DrexRoutingResult
from brain.routing.escalation import EscalationManager, FailureType
from brain.routing.engine import (
    TaskClassifier,
    CandidateFilter,
    DynamicRouter,
    RouteRequest,
    RouteDecision,
    TaskContext,
)


def _make_candidate(
    suffix: str,
    provider: str = "mock-provider-a",
    context: int = 65536,
    tools: bool = True,
    vision: bool = False,
    privacy: str = "zero_retention",
    quality: float = 0.80,
    ttft_ms: float = 300.0,
    cost_per_m: float = 0.50,
    successes: int = 20,
    failures: int = 1,
    is_pinned: bool = False,
    is_banned: bool = False,
    is_cooldown: bool = False,
    cooldown_s: float = 0.0,
) -> CandidateMetrics:
    m_id = f"mock-model-{suffix}"
    return CandidateMetrics(
        model_id=m_id,
        provider=provider,
        route_id=f"{provider}/{m_id}",
        context_window=context,
        pricing={"input_per_million": cost_per_m, "output_per_million": cost_per_m * 2},
        capabilities={"tools": tools, "vision": vision, "streaming": True},
        privacy_policy=privacy,
        measured_quality=quality,
        measured_ttft_ms=ttft_ms,
        success_count=successes,
        failure_count=failures,
        is_pinned=is_pinned,
        is_banned=is_banned,
        is_cooldown=is_cooldown,
        cooldown_remaining_s=cooldown_s,
    )


# ============================================================================
# 1. Requirement Profiles Tests
# ============================================================================

class TestRequirementProfiles:
    def test_soft_objectives_normalization(self):
        objs = SoftObjectives(quality=2.0, ttft=1.0, cost=1.0, reliability=0.0).normalized()
        assert round(objs.quality + objs.ttft + objs.cost + objs.reliability, 2) == 1.0
        assert objs.quality == 0.5
        assert objs.ttft == 0.25

    def test_soft_objectives_zero_fallback(self):
        objs = SoftObjectives(quality=0.0, ttft=0.0, cost=0.0, reliability=0.0).normalized()
        assert objs.quality == 0.25
        assert objs.ttft == 0.25

    def test_load_and_save_profiles(self, tmp_path):
        prof_file = tmp_path / "profiles.json"
        p_dict = {
            "custom_role": RequirementProfile(
                name="custom_role",
                description="Custom task requirements",
                hard_constraints=HardConstraints(tool_calling=True, min_context=16384),
                soft_objectives=SoftObjectives(quality=0.5, ttft=0.2, cost=0.2, reliability=0.1),
            )
        }
        save_profiles(p_dict, path=prof_file)
        assert prof_file.exists()

        loaded = load_profiles(path=prof_file)
        assert "custom_role" in loaded
        assert loaded["custom_role"].hard_constraints.tool_calling is True
        assert loaded["custom_role"].hard_constraints.min_context == 16384

    def test_get_profile_fallback(self, tmp_path):
        prof_file = tmp_path / "profiles.json"
        save_profiles({}, path=prof_file)
        p = get_profile("nonexistent_profile_xyz", path=prof_file)
        assert p.name in ("nonexistent_profile_xyz", "main")


# ============================================================================
# 2. Task Classifier Tests
# ============================================================================

class TestTaskClassifier:
    def setup_method(self):
        self.classifier = TaskClassifier()

    def test_detect_code_generation(self):
        prompt = "def calculate_matrix_determinant(matrix):\n    return np.linalg.det(matrix)"
        ctx = self.classifier.classify(prompt)
        assert ctx.task_type == "code_generation"
        assert ctx.language == "code"

    def test_detect_planning(self):
        prompt = "We need an architecture migration roadmap and new ADR specifications."
        ctx = self.classifier.classify(prompt)
        assert ctx.task_type == "planning"

    def test_detect_summarization(self):
        prompt = "Please summarize the meeting notes and provide a tldr of key decisions."
        ctx = self.classifier.classify(prompt)
        assert ctx.task_type == "summarization"

    def test_detect_vision_needed(self):
        prompt = "Review the attached UI screenshot diagram.png for layout inconsistencies."
        ctx = self.classifier.classify(prompt)
        assert ctx.vision_needed is True
        assert ctx.task_type == "visual_analysis"

    def test_detect_arabic_language(self):
        prompt = "قم بكتابة دالة للتحقق من صحة المدخلات"
        ctx = self.classifier.classify(prompt)
        assert ctx.language == "ar"

    def test_complexity_classification(self):
        short_prompt = "Hello world"
        assert self.classifier.classify(short_prompt).complexity == "low"

        medium_prompt = "Write a function that connects to sqlite and queries user tables with error handling."
        assert self.classifier.classify(medium_prompt).complexity in ("low", "medium")

        high_prompt = "Refactor the authentication subsystem. Step 1: parse tokens. Step 2: verify signatures.\n" + ("x" * 2600)
        assert self.classifier.classify(high_prompt).complexity == "high"


# ============================================================================
# 3. Candidate Filter Tests
# ============================================================================

class TestCandidateFilter:
    def setup_method(self):
        self.filter_engine = CandidateFilter()
        self.profile = RequirementProfile(
            name="test_profile",
            hard_constraints=HardConstraints(
                tool_calling=True,
                min_context=32768,
                vision=False,
                privacy="zero_retention",
            ),
        )

    def test_filters_out_lacking_tools(self):
        c_tools = _make_candidate("has-tools", tools=True)
        c_no_tools = _make_candidate("no-tools", tools=False)
        task = TaskContext(tools_needed=True)

        passed, rejections = self.filter_engine.filter([c_tools, c_no_tools], self.profile, task)
        assert len(passed) == 1
        assert passed[0].route_id == c_tools.route_id
        assert c_no_tools.route_id in rejections

    def test_filters_out_insufficient_context(self):
        c_large = _make_candidate("large-ctx", context=131072)
        c_small = _make_candidate("small-ctx", context=16384)
        task = TaskContext(prompt_tokens=1000)

        passed, rejections = self.filter_engine.filter([c_large, c_small], self.profile, task)
        assert len(passed) == 1
        assert passed[0].route_id == c_large.route_id
        assert c_small.route_id in rejections

    def test_filters_out_cooldown_and_banned(self):
        c_ok = _make_candidate("active")
        c_cooldown = _make_candidate("cooling", is_cooldown=True, cooldown_s=45.0)
        c_banned = _make_candidate("banned", is_banned=True)
        task = TaskContext()

        passed, rejections = self.filter_engine.filter([c_ok, c_cooldown, c_banned], self.profile, task)
        assert len(passed) == 1
        assert passed[0].route_id == c_ok.route_id
        assert c_cooldown.route_id in rejections
        assert c_banned.route_id in rejections

    def test_filters_out_privacy_violation(self):
        c_clean = _make_candidate("clean", privacy="zero_retention")
        c_public = _make_candidate("public", privacy="public_retention")
        task = TaskContext()

        passed, rejections = self.filter_engine.filter([c_clean, c_public], self.profile, task)
        assert len(passed) == 1
        assert passed[0].route_id == c_clean.route_id
        assert c_public.route_id in rejections


# ============================================================================
# 4. Expected Utility Scorer Tests
# ============================================================================

class TestExpectedUtilityScorer:
    def setup_method(self):
        self.scorer = ExpectedUtilityScorer(cache_affinity_bonus=0.15)
        self.profile = RequirementProfile(
            name="scorer_profile",
            soft_objectives=SoftObjectives(quality=0.5, ttft=0.2, cost=0.2, reliability=0.1),
        )

    def test_higher_quality_yields_higher_score(self):
        c_high_q = _make_candidate("high-q", quality=0.95, ttft_ms=500.0)
        c_low_q = _make_candidate("low-q", quality=0.40, ttft_ms=500.0)

        s_high = self.scorer.score_candidate(c_high_q, self.profile)
        s_low = self.scorer.score_candidate(c_low_q, self.profile)

        assert s_high.utility_score > s_low.utility_score
        assert s_high.quality_score > s_low.quality_score
        assert s_high.ci_lower <= s_high.quality_score <= s_high.ci_upper

    def test_cache_affinity_bonus(self):
        c1 = _make_candidate("session-active", quality=0.80)
        s_no_cache = self.scorer.score_candidate(c1, self.profile, session_active_model=None)
        s_with_cache = self.scorer.score_candidate(c1, self.profile, session_active_model=c1.model_id)

        assert s_with_cache.utility_score > s_no_cache.utility_score
        assert s_with_cache.cache_affinity_bonus == 0.15
        assert s_no_cache.cache_affinity_bonus == 0.0

    def test_pinned_model_bonus(self):
        c_normal = _make_candidate("normal", is_pinned=False)
        c_pinned = _make_candidate("pinned", is_pinned=True)

        s_normal = self.scorer.score_candidate(c_normal, self.profile)
        s_pinned = self.scorer.score_candidate(c_pinned, self.profile)

        assert s_pinned.utility_score > s_normal.utility_score


# ============================================================================
# 5. Bandit Router Tests
# ============================================================================

class TestBanditRouter:
    def test_undersampled_identification(self):
        bandit = BanditRouter(min_samples_threshold=10)
        c_fresh = _make_candidate("fresh", successes=2, failures=0)
        c_mature = _make_candidate("mature", successes=50, failures=2)

        undersampled = bandit.get_undersampled_candidates([c_fresh, c_mature])
        assert len(undersampled) == 1
        assert undersampled[0].route_id == c_fresh.route_id

    def test_budget_cap_stops_exploration(self):
        bandit = BanditRouter(budget_cap_usd=0.05)
        c_fresh = _make_candidate("fresh", successes=1, failures=0)

        assert bandit.should_explore([c_fresh], force_explore=True) is True
        bandit.record_decision(is_exploration=True, cost_usd=0.06)
        assert bandit.should_explore([c_fresh], force_explore=True) is False


# ============================================================================
# 6. Drex Router Tests
# ============================================================================

class TestDrexRouter:
    def test_decisive_score_bypasses_drex(self):
        dt_mock = MagicMock()
        drex_router = DrexRouter(decision_taker=dt_mock, borderline_margin=0.05)

        c1 = _make_candidate("winner")
        c2 = _make_candidate("loser")
        scorer = ExpectedUtilityScorer()
        prof = RequirementProfile(name="p")
        scored = [
            ScoredCandidate(
                metrics=c1, utility_score=0.90, quality_score=0.9, ttft_score=0.9,
                cost_score=0.9, reliability_score=0.9, cache_affinity_bonus=0,
                ci_lower=0.8, ci_upper=0.95, confidence=0.9, estimated_cost_usd=0.001, explanation="",
            ),
            ScoredCandidate(
                metrics=c2, utility_score=0.60, quality_score=0.6, ttft_score=0.6,
                cost_score=0.6, reliability_score=0.6, cache_affinity_bonus=0,
                ci_lower=0.5, ci_upper=0.7, confidence=0.8, estimated_cost_usd=0.001, explanation="",
            ),
        ]

        res = drex_router.decide(scored, task_summary="Decisive task")
        assert res.source == "deterministic"
        assert res.is_borderline is False
        assert dt_mock.decide_provider.called is False

    def test_borderline_invokes_drex_and_accepts_confident_choice(self):
        dt_mock = MagicMock()
        dt_mock.decide_provider.return_value = MagicMock(
            source="drex",
            value="mock-provider-a/mock-model-cand2",
            confidence=0.85,
        )
        drex_router = DrexRouter(decision_taker=dt_mock, borderline_margin=0.10)

        c1 = _make_candidate("cand1")
        c2 = _make_candidate("cand2")
        scored = [
            ScoredCandidate(
                metrics=c1, utility_score=0.81, quality_score=0.8, ttft_score=0.8,
                cost_score=0.8, reliability_score=0.8, cache_affinity_bonus=0,
                ci_lower=0.7, ci_upper=0.9, confidence=0.85, estimated_cost_usd=0.001, explanation="",
            ),
            ScoredCandidate(
                metrics=c2, utility_score=0.80, quality_score=0.8, ttft_score=0.8,
                cost_score=0.8, reliability_score=0.8, cache_affinity_bonus=0,
                ci_lower=0.7, ci_upper=0.9, confidence=0.85, estimated_cost_usd=0.001, explanation="",
            ),
        ]

        res = drex_router.decide(scored, task_summary="Borderline task")
        assert dt_mock.decide_provider.called is True
        assert res.source == "drex"
        assert res.selected.metrics.route_id == c2.route_id
        assert res.confidence == 0.85

    def test_drex_fallback_on_low_confidence(self):
        dt_mock = MagicMock()
        dt_mock.decide_provider.return_value = MagicMock(
            source="drex",
            value="mock-provider-a/mock-model-cand2",
            confidence=0.30,  # Below 0.55 threshold
        )
        drex_router = DrexRouter(decision_taker=dt_mock, borderline_margin=0.10, confidence_threshold=0.55)

        c1 = _make_candidate("cand1")
        c2 = _make_candidate("cand2")
        scored = [
            ScoredCandidate(
                metrics=c1, utility_score=0.81, quality_score=0.8, ttft_score=0.8,
                cost_score=0.8, reliability_score=0.8, cache_affinity_bonus=0,
                ci_lower=0.7, ci_upper=0.9, confidence=0.85, estimated_cost_usd=0.001, explanation="",
            ),
            ScoredCandidate(
                metrics=c2, utility_score=0.80, quality_score=0.8, ttft_score=0.8,
                cost_score=0.8, reliability_score=0.8, cache_affinity_bonus=0,
                ci_lower=0.7, ci_upper=0.9, confidence=0.85, estimated_cost_usd=0.001, explanation="",
            ),
        ]

        res = drex_router.decide(scored, task_summary="Borderline task")
        assert res.source == "drex_fallback"
        assert res.selected.metrics.route_id == c1.route_id  # Falls back to top utility scorer


# ============================================================================
# 7. Escalation Manager Tests
# ============================================================================

class TestEscalationManager:
    def setup_method(self):
        self.escalation = EscalationManager()

    def test_escalates_to_higher_quality_on_tool_failure(self):
        c_weak = _make_candidate("weak", quality=0.55)
        c_strong = _make_candidate("strong", quality=0.90)

        scorer = ExpectedUtilityScorer()
        prof = RequirementProfile(name="p")
        scored = scorer.score_all([c_weak, c_strong], prof)

        escalated = self.escalation.select_escalation_candidate(
            session_id="sess_123",
            failed_route_id=c_weak.route_id,
            failure_type=FailureType.INVALID_TOOL_CALL,
            available_candidates=scored,
        )

        assert escalated is not None
        assert escalated.metrics.route_id == c_strong.route_id

        # Verify failed route is not re-selected
        history = self.escalation.get_escalation_history("sess_123")
        assert len(history) == 1
        assert history[0].failed_route_id == c_weak.route_id
        assert history[0].state_preserved is True


# ============================================================================
# 8. Dynamic Router End-to-End Pipeline Tests
# ============================================================================

class TestDynamicRouterPipeline:
    def setup_method(self):
        self.router = DynamicRouter()
        self.c1 = _make_candidate("speed", ttft_ms=100.0, quality=0.70, cost_per_m=0.10)
        self.c2 = _make_candidate("quality", ttft_ms=600.0, quality=0.95, cost_per_m=2.00)
        self.c3 = _make_candidate("vision", vision=True, quality=0.85)
        self.router.set_candidate_pool([self.c1, self.c2, self.c3])

    def test_routing_fast_profile(self):
        req = RouteRequest(
            prompt="Quick lookup query",
            profile_name="fast",
            prompt_tokens=200,
        )
        dec = self.router.route(req)
        assert dec.selected_route_id == self.c1.route_id
        assert dec.resolved_profile == "fast"
        assert len(dec.fallback_chain) > 0

    def test_routing_multimodal_demand(self):
        req = RouteRequest(
            prompt="Review this wireframe diagram.png",
            profile_name="main",
            images=[{"type": "mock_img"}],
        )
        dec = self.router.route(req)
        assert dec.selected_route_id == self.c3.route_id
        assert dec.task_context.vision_needed is True

    def test_session_tool_loop_cache_retention(self):
        req1 = RouteRequest(
            prompt="Start coding agent",
            profile_name="main",
            session_id="tool_session_42",
        )
        dec1 = self.router.route(req1)
        first_model = dec1.selected_model

        # Next iteration in tool loop
        req2 = RouteRequest(
            prompt="Continue iteration with next tool call",
            profile_name="main",
            session_id="tool_session_42",
            is_tool_loop=True,
        )
        dec2 = self.router.route(req2)
        assert dec2.selected_model == first_model
        assert dec2.decision_source == "cache_retention"
        assert dec2.handoff_occurred is False

    def test_escalation_workflow(self):
        req = RouteRequest(
            prompt="Execute complex refactoring",
            profile_name="main",
            session_id="esc_session_99",
        )
        dec1 = self.router.route(req)
        failed_route = dec1.selected_route_id

        # Escalate on failure
        esc_dec = self.router.escalate(
            session_id="esc_session_99",
            failed_route_id=failed_route,
            failure_type=FailureType.TEST_FAILURE,
            request=req,
        )

        assert esc_dec.selected_route_id != failed_route
        assert esc_dec.decision_source == "escalation"
        assert esc_dec.handoff_occurred is True

    def test_explain_trace_recording(self):
        req = RouteRequest(prompt="Explain test trace", profile_name="main")
        dec = self.router.route(req)
        exp = self.router.explain(dec.request_id)

        assert exp is not None
        assert exp.request_id == dec.request_id
        assert exp.decision.selected_route_id == dec.selected_route_id
        assert len(exp.all_scored_candidates) > 0
