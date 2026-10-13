"""tests/routing/test_learning_loop.py — Tests for online learning, drift detection, Drex calibration, and explain engine.

Rules strictly adhered to:
- Never hardcode model names in test code (dynamically generated identifiers).
- Fully test online feedback loop, Bayesian updating, EMA, sample size N, time decay.
- Fully test drift detection and automatic demotion with clear explanation.
- Fully test Drex trust calibration and dynamic weight/threshold adjustments.
- Fully test trace explain engine with all required schema elements.
"""

import math
import sqlite3
import time
import uuid
from typing import List

import pytest
from fastapi.testclient import TestClient

from brain.api.app import create_app
from brain.routing.learning import (
    DriftDetector,
    DrexTrustCalibrator,
    OnlineLearningRouter,
    OracleOutcome,
    QualityEstimate,
    RouteTrace,
    TraceExplainEngine,
)


def _dyn_model(prefix: str = "mod") -> str:
    """Generate a dynamic, non-hardcoded model identifier."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ============================================================================
# 1. Oracle Outcome & Signals Tests
# ============================================================================

def test_oracle_outcome_all_pass():
    outcome = OracleOutcome(
        tests_pass=True,
        tool_calls_valid=True,
        user_accepted=True,
        no_retry_needed=True,
        cost=0.002,
        latency=120.0,
        error=False,
    )
    score = outcome.compute_quality_score()
    assert score == 1.0


def test_oracle_outcome_error_zero_score():
    outcome = OracleOutcome(
        tests_pass=True,
        tool_calls_valid=True,
        user_accepted=True,
        no_retry_needed=True,
        error=True,
    )
    score = outcome.compute_quality_score()
    assert score == 0.0


def test_oracle_outcome_partial_signals():
    # Only tests pass (weight 0.35) and tool calls invalid (weight 0.25)
    outcome = OracleOutcome(
        tests_pass=True,
        tool_calls_valid=False,
        error=False,
    )
    score = outcome.compute_quality_score()
    expected = 0.35 / (0.35 + 0.25)
    assert abs(score - expected) < 0.01


# ============================================================================
# 2. Online Feedback Loop & Bayesian / EMA Updating Tests
# ============================================================================

def test_bayesian_and_ema_updating():
    model_name = _dyn_model("test_bayes")
    task_name = f"task_{uuid.uuid4().hex[:6]}"

    router = OnlineLearningRouter()
    est_initial = router.get_estimate(model_name, task_name)

    assert est_initial.sample_size == 0
    assert est_initial.alpha == 1.0
    assert est_initial.beta == 1.0
    assert est_initial.bayesian_mean == 0.5

    # Record 5 positive outcomes
    for i in range(5):
        req_id = f"req_{uuid.uuid4().hex[:6]}"
        outcome = OracleOutcome(
            tests_pass=True,
            tool_calls_valid=True,
            user_accepted=True,
            no_retry_needed=True,
            latency=100.0,
            cost=0.001,
            error=False,
        )
        res = router.record_outcome(req_id, outcome, model_id=model_name, task_type=task_name)
        assert res["success"] is True

    est_after = router.get_estimate(model_name, task_name)
    assert est_after.sample_size == 5
    assert est_after.effective_n == pytest.approx(5.0, abs=1e-3)
    assert est_after.alpha == pytest.approx(6.0, abs=1e-3)
    assert est_after.beta == 1.0         # prior + 0 = 1.0
    assert est_after.bayesian_mean == pytest.approx(6.0 / 7.0, abs=1e-3)
    assert est_after.ema_quality > 0.60
    assert est_after.ema_error_rate == 0.0
    assert est_after.ema_tool_accuracy == 1.0


# ============================================================================
# 3. Time Decay Tests
# ============================================================================

def test_time_decay_observations():
    model_name = _dyn_model("decay_mod")
    task_name = f"task_{uuid.uuid4().hex[:6]}"

    est = QualityEstimate(model_id=model_name, task_type=task_name)
    est.alpha = 11.0  # 10 observed successes on top of prior 1.0
    est.beta = 1.0
    est.effective_n = 10.0

    # Half life is 100 seconds; advance 100 seconds
    half_life = 100.0
    est.apply_time_decay(elapsed_seconds=half_life, half_life_seconds=half_life)

    # After 1 half-life, (alpha - 1.0) should be halved to 5.0 => alpha = 6.0
    assert abs(est.alpha - 6.0) < 0.05
    assert abs(est.effective_n - 5.0) < 0.05

    # After another half-life => alpha should be 1.0 + 2.5 = 3.5
    est.apply_time_decay(elapsed_seconds=half_life, half_life_seconds=half_life)
    assert abs(est.alpha - 3.5) < 0.05
    assert abs(est.effective_n - 2.5) < 0.05


# ============================================================================
# 4. Drift Detection & Automatic Demotion Tests
# ============================================================================

def test_drift_detection_error_spike_and_demotion():
    model_name = _dyn_model("drift_err")
    task_name = f"task_{uuid.uuid4().hex[:6]}"

    detector = DriftDetector(min_recent_samples=3, error_spike_threshold=0.30, demotion_penalty=0.20)
    router = OnlineLearningRouter(drift_detector=detector)

    # 1. Warm up with clean runs so baseline error rate is 0.0
    for _ in range(5):
        req_id = f"req_{uuid.uuid4().hex[:6]}"
        outcome = OracleOutcome(tests_pass=True, tool_calls_valid=True, error=False)
        router.record_outcome(req_id, outcome, model_id=model_name, task_type=task_name)

    est = router.get_estimate(model_name, task_name)
    assert not est.is_demoted
    assert est.demotion_penalty == 1.0

    # 2. Trigger sudden error spike (3 consecutive errors)
    for _ in range(3):
        req_id = f"req_{uuid.uuid4().hex[:6]}"
        outcome = OracleOutcome(error=True)
        res = router.record_outcome(req_id, outcome, model_id=model_name, task_type=task_name)

    est_demoted = router.get_estimate(model_name, task_name)
    assert est_demoted.is_demoted is True
    assert est_demoted.demotion_penalty == 0.20
    assert "Sudden error spike" in (est_demoted.demoted_reason or "")
    assert len(router.demotion_log) >= 1
    assert router.demotion_log[-1]["trigger_type"] == "error_spike"

    # Score should be heavily penalized by demotion factor
    assert est_demoted.score < 0.25


def test_drift_detection_tool_accuracy_regression():
    model_name = _dyn_model("drift_tool")
    task_name = f"task_{uuid.uuid4().hex[:6]}"

    detector = DriftDetector(min_recent_samples=3, tool_accuracy_drop_threshold=0.25)
    router = OnlineLearningRouter(drift_detector=detector)

    # Warm up with valid tools
    for _ in range(4):
        req_id = f"req_{uuid.uuid4().hex[:6]}"
        outcome = OracleOutcome(tests_pass=True, tool_calls_valid=True, error=False)
        router.record_outcome(req_id, outcome, model_id=model_name, task_type=task_name)

    # Inject tool validation failures
    for _ in range(3):
        req_id = f"req_{uuid.uuid4().hex[:6]}"
        outcome = OracleOutcome(tests_pass=True, tool_calls_valid=False, error=False)
        router.record_outcome(req_id, outcome, model_id=model_name, task_type=task_name)

    est = router.get_estimate(model_name, task_name)
    assert est.is_demoted is True
    assert "Tool accuracy regression" in (est.demoted_reason or "")


def test_demoted_model_automatic_recovery():
    model_name = _dyn_model("recover_mod")
    task_name = f"task_{uuid.uuid4().hex[:6]}"

    detector = DriftDetector(min_recent_samples=3)
    router = OnlineLearningRouter(drift_detector=detector)

    # Cause demotion
    for _ in range(3):
        req_id = f"req_{uuid.uuid4().hex[:6]}"
        outcome = OracleOutcome(error=True)
        router.record_outcome(req_id, outcome, model_id=model_name, task_type=task_name)

    est = router.get_estimate(model_name, task_name)
    assert est.is_demoted is True

    # Now recover with clean consecutive successful outcomes
    for _ in range(4):
        req_id = f"req_{uuid.uuid4().hex[:6]}"
        outcome = OracleOutcome(
            tests_pass=True,
            tool_calls_valid=True,
            user_accepted=True,
            no_retry_needed=True,
            error=False,
        )
        router.record_outcome(req_id, outcome, model_id=model_name, task_type=task_name)

    est_recovered = router.get_estimate(model_name, task_name)
    assert est_recovered.is_demoted is False
    assert est_recovered.demotion_penalty == 1.0


# ============================================================================
# 5. Drex Trust Calibration Tests
# ============================================================================

def test_drex_trust_calibration_disabling_underperforming():
    decision_type = f"dec_{uuid.uuid4().hex[:6]}"
    calibrator = DrexTrustCalibrator(min_evals_for_calibration=5)

    # Drex fails while deterministic scoring succeeds
    for _ in range(5):
        calibrator.record_outcome(
            decision_type=decision_type,
            drex_success=False,
            deterministic_success=True,
            drex_confidence=0.85,
        )

    rec = calibrator.records[decision_type]
    assert rec.drex_accuracy == 0.0
    assert rec.deterministic_accuracy == 1.0
    assert rec.enabled is False
    assert rec.weight == 0.0
    assert "Disabled Drex" in rec.history[-1]["explanation"]


def test_drex_trust_calibration_promoting_value():
    decision_type = f"dec_{uuid.uuid4().hex[:6]}"
    calibrator = DrexTrustCalibrator(min_evals_for_calibration=5)

    # Drex outperforms deterministic utility
    for _ in range(5):
        calibrator.record_outcome(
            decision_type=decision_type,
            drex_success=True,
            deterministic_success=False,
            drex_confidence=0.90,
        )

    rec = calibrator.records[decision_type]
    assert rec.drex_accuracy == 1.0
    assert rec.deterministic_accuracy == 0.0
    assert rec.enabled is True
    assert rec.weight > 0.50
    assert rec.confidence_threshold <= 0.65
    assert "Promoted Drex trust" in rec.history[-1]["explanation"]


# ============================================================================
# 6. Route Trace & Explain Engine Tests
# ============================================================================

def test_route_trace_and_explain_engine():
    cand_1 = _dyn_model("cand_a")
    cand_2 = _dyn_model("cand_b")
    candidates = [cand_1, cand_2]

    req_id = f"req_{uuid.uuid4().hex[:8]}"
    router = OnlineLearningRouter()

    # Pre-warm cand_1 with positive ratings so it gets higher score
    for _ in range(3):
        r_id = f"init_{uuid.uuid4().hex[:6]}"
        outcome = OracleOutcome(tests_pass=True, user_accepted=True, error=False)
        router.record_outcome(r_id, outcome, model_id=cand_1, task_type="reasoning")

    # Select route
    trace = router.select_route(
        request_id=req_id,
        candidates=candidates,
        task_data={"task_type": "reasoning", "max_cost": 0.05},
        drex_recommendation={"recommended_model": cand_1, "confidence": 0.92},
    )

    assert trace.request_id == req_id
    assert trace.task_classification["task_type"] == "reasoning"
    assert trace.candidates == candidates
    assert cand_1 in trace.scores
    assert cand_2 in trace.scores
    assert trace.final_choice["model_id"] == cand_1
    assert "drex_recommendation" in trace.to_dict()

    # Now explain via explain engine
    explanation = router.explain(req_id)
    assert explanation["request_id"] == req_id
    assert "task_classification" in explanation
    assert "candidates" in explanation
    assert "constraints" in explanation
    assert "scores" in explanation
    assert "drex_recommendation" in explanation
    assert "final_choice" in explanation
    assert "plain_explanation" in explanation
    assert cand_1 in explanation["plain_explanation"]


# ============================================================================
# 7. SQLite Persistence Tests
# ============================================================================

def test_sqlite_persistence_of_traces_and_demotions():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    router = OnlineLearningRouter(conn=conn)
    model_name = _dyn_model("persisted_mod")
    task_name = "code_generation"
    req_id = f"req_{uuid.uuid4().hex[:8]}"

    # Select route
    router.select_route(
        request_id=req_id,
        candidates=[model_name],
        task_data={"task_type": task_name},
    )

    # Verify trace table exists and contains record
    row = conn.execute("SELECT * FROM routing_traces WHERE request_id = ?", (req_id,)).fetchone()
    assert row is not None

    # Demote model through errors
    for _ in range(4):
        err_id = f"err_{uuid.uuid4().hex[:6]}"
        router.record_outcome(err_id, OracleOutcome(error=True), model_id=model_name, task_type=task_name)

    d_row = conn.execute("SELECT * FROM routing_demotions WHERE model_id = ?", (model_name,)).fetchone()
    assert d_row is not None
    assert d_row["model_id"] == model_name


# ============================================================================
# 8. API Endpoint /api/routing/explain/{id} Tests
# ============================================================================

def test_fastapi_routing_explain_endpoint():
    from brain.api.security import get_or_create_auth_token
    token = get_or_create_auth_token()
    app = create_app()
    client = TestClient(app)

    req_id = f"req_{uuid.uuid4().hex[:8]}"
    model_name = _dyn_model("api_cand")

    # Record trace in learning router
    from brain.routing.learning import get_learning_router
    lr = get_learning_router()
    lr.select_route(
        request_id=req_id,
        candidates=[model_name],
        task_data={"task_type": "api_test"},
    )

    resp = client.get(f"/api/routing/explain/{req_id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()

    assert data["request_id"] == req_id
    assert "task_classification" in data
    assert "candidates" in data
    assert "constraints" in data
    assert "scores" in data
    assert "drex_recommendation" in data
    assert "final_choice" in data
    assert data["final_choice"]["model_id"] == model_name


# ============================================================================
# 9. CLI cm route explain Tests
# ============================================================================

def test_cli_cm_route_explain(capsys):
    import argparse
    from cli.cm import cmd_route

    req_id = f"req_{uuid.uuid4().hex[:8]}"
    model_name = _dyn_model("cli_cand")

    from brain.routing.learning import get_learning_router
    lr = get_learning_router()
    lr.select_route(
        request_id=req_id,
        candidates=[model_name],
        task_data={"task_type": "cli_test"},
    )

    # Mock CMClient
    class DummyClient:
        def request(self, method, path, body=None, curl=False, api_only=False):
            assert method == "GET"
            assert path in (f"/api/routing/explain/{req_id}", f"/api/v1/routing/explain/{req_id}")
            return 200, lr.explain(req_id)

    args = argparse.Namespace(
        subcommand="explain",
        strategy=req_id,
        req_id=req_id,
        curl=False,
        api=False,
        json=False,
        model=None,
    )

    ret = cmd_route(DummyClient(), args)
    assert ret == 0
    captured = capsys.readouterr().out
    assert "Routing Decision Explanation" in captured or "Routing Trace Explanation" in captured
    assert model_name in captured

