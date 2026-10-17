"""tests/routing/test_unmeasured_route_rank.py — Unit test verifying unmeasured route ranking.

Directive 4 requirement:
An unmeasured route (assigned pessimistic prior Q0 <= 0.10) can NEVER outrank a route with
measured successes during deterministic expected utility scoring, except through the capped exploration budget.
"""

import pytest
from brain.routing.scorer import ExpectedUtilityScorer, CandidateMetrics
from brain.routing.profiles import RequirementProfile, SoftObjectives
from brain.routing.engine import DynamicRouter, RouteRequest


def test_unmeasured_route_cannot_outrank_measured_route():
    """Verify an unmeasured route (Q0=0.10) scores strictly below a route with measured successes."""
    scorer = ExpectedUtilityScorer()
    profile = RequirementProfile(
        name="standard",
        objectives=SoftObjectives(quality=0.55, ttft=0.15, cost=0.15, reliability=0.15)
    )

    measured = CandidateMetrics(
        model_id="ministral-8b-latest",
        provider="mistral",
        route_id="mistral/ministral-8b-latest",
        measured_quality=0.975,
        measured_ttft_ms=3758.0,
        success_count=22,
        failure_count=0,
        is_measured=True,
    )

    unmeasured = CandidateMetrics(
        model_id="qwen-30b-unmeasured",
        provider="openrouter",
        route_id="openrouter/qwen-30b-unmeasured",
        measured_quality=0.10,
        measured_ttft_ms=3758.0,
        success_count=0,
        failure_count=0,
        is_measured=False,
    )

    scored_measured = scorer.score_candidate(measured, profile)
    scored_unmeasured = scorer.score_candidate(unmeasured, profile)

    # Measured route utility must be substantially higher than unmeasured
    assert scored_measured.utility_score > scored_unmeasured.utility_score
    # Unmeasured route quality score must reflect pessimistic prior Q0 = 0.10
    assert scored_unmeasured.quality_score == 0.10
    # Measured quality posterior mean is ~0.998 with 22 successes and 0 failures
    assert 0.95 <= scored_measured.quality_score <= 1.0
    # Absolute utility gap is wide (> 0.40)
    assert scored_measured.utility_score - scored_unmeasured.utility_score > 0.40


def test_router_never_selects_unmeasured_in_deterministic_mode():
    """Verify DynamicRouter selects the measured candidate over unmeasured when Drex and exploration are disabled."""
    measured = CandidateMetrics(
        model_id="ministral-8b-latest",
        provider="mistral",
        route_id="mistral/ministral-8b-latest",
        measured_quality=0.975,
        measured_ttft_ms=3758.0,
        success_count=22,
        failure_count=0,
        is_measured=True,
    )
    unmeasured = CandidateMetrics(
        model_id="hypothetical-model",
        provider="openrouter",
        route_id="openrouter/hypothetical-model",
        measured_quality=0.10,
        measured_ttft_ms=3758.0,
        success_count=0,
        failure_count=0,
        is_measured=False,
    )

    router = DynamicRouter()
    req = RouteRequest(
        prompt="Write a test script",
        custom_candidates=[measured, unmeasured],
        force_explore=False
    )
    decision = router.route(req)

    assert decision.selected_route_id == "mistral/ministral-8b-latest"
    assert decision.selected_route_id != "openrouter/hypothetical-model"
