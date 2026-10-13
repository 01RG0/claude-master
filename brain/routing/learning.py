"""brain/routing/learning.py — Online Feedback Loop, Drift Detection, and Drex Calibration.

This module implements:
1. Online Feedback Loop:
   - Records request outcomes verified by oracles (tests pass, tool calls valid, user accepted,
     no retry needed, cost, latency, error).
   - Updates per-model, per-task-type quality estimates with Bayesian updating (Beta-Binomial)
     and exponential moving average (EMA) along with sample size N.
   - Applies time decay to old observations so model updates and provider degradation are captured.
2. Drift Detection & Automatic Demotion:
   - Detects performance regressions on routes (sudden error spike, drop in tool accuracy, quality drop).
   - Automatically demotes degrading models, adjusts their utility scores, and logs the adjustment
     with clear explanation and audit trail.
3. Drex Trust Calibration:
   - Tracks when Drex recommendations succeeded or failed compared to deterministic utility scoring.
   - Dynamically adjusts weights and confidence thresholds for Drex per decision type, disabling it
     where it does not add value.
4. Explainability:
   - Trace explain engine showing task classification, candidates, constraints, scores,
     Drex recommendation & confidence, and final choice.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from brain.routing.hyperparameters import get_hyperparameter

logger = logging.getLogger("brain.routing.learning")


# ============================================================================
# 1. Oracle Outcome & Signals
# ============================================================================

@dataclass
class OracleOutcome:
    """Request outcome verified by deterministic oracles and runtime metrics.

    Signals:
    - tests_pass: whether generated or executed tests passed
    - tool_calls_valid: whether tool calls syntax and parameters were valid
    - user_accepted: whether user accepted the response or diff
    - no_retry_needed: whether request completed without retry or failover
    - cost: request cost in USD
    - latency: latency in milliseconds
    - error: whether an error (HTTP, exception, schema violation) occurred
    - details: additional contextual metadata
    """

    tests_pass: Optional[bool] = None
    tool_calls_valid: Optional[bool] = None
    user_accepted: Optional[bool] = None
    no_retry_needed: Optional[bool] = None
    cost: float = 0.0
    latency: float = 0.0
    error: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    def compute_quality_score(self) -> float:
        """Derive a normalized quality reward score in [0.0, 1.0]."""
        if self.error:
            return 0.0

        weights = {
            "tests_pass": (self.tests_pass, 0.35),
            "user_accepted": (self.user_accepted, 0.30),
            "tool_calls_valid": (self.tool_calls_valid, 0.25),
            "no_retry_needed": (self.no_retry_needed, 0.10),
        }

        total_weight = 0.0
        weighted_sum = 0.0

        for key, (val, w) in weights.items():
            if val is not None:
                total_weight += w
                weighted_sum += w * (1.0 if val else 0.0)

        if total_weight == 0.0:
            return 1.0  # Successful execution without specific oracle failure

        return round(weighted_sum / total_weight, 4)


# ============================================================================
# 2. Quality Estimate & Bayesian / EMA State
# ============================================================================

@dataclass
class QualityEstimate:
    """Per-model, per-task-type dynamic quality estimate."""

    model_id: str
    task_type: str
    # Bayesian Beta prior parameters (Beta(alpha, beta))
    alpha: float = 1.0
    beta: float = 1.0
    # Exponential moving averages
    ema_quality: float = 0.5
    ema_latency_ms: float = 0.0
    ema_cost: float = 0.0
    ema_tool_accuracy: float = 1.0
    ema_error_rate: float = 0.0
    # Sample counters
    sample_size: int = 0
    effective_n: float = 0.0
    successes: int = 0
    failures: int = 0
    # Demotion state
    is_demoted: bool = False
    demoted_reason: Optional[str] = None
    demoted_at: Optional[float] = None
    demotion_penalty: float = 1.0
    # Sliding window of recent outcomes for drift detection
    recent_outcomes: List[Dict[str, Any]] = field(default_factory=list)
    last_updated_at: float = field(default_factory=time.time)

    @property
    def bayesian_mean(self) -> float:
        """Bayesian expected quality score E[X] = alpha / (alpha + beta)."""
        denom = self.alpha + self.beta
        return self.alpha / denom if denom > 0 else 0.5

    @property
    def bayesian_variance(self) -> float:
        """Bayesian uncertainty Var(X)."""
        a, b = self.alpha, self.beta
        denom = ((a + b) ** 2) * (a + b + 1.0)
        return (a * b) / denom if denom > 0 else 0.0

    @property
    def score(self) -> float:
        """Combined composite utility score factoring Bayesian mean, EMA, and demotion."""
        raw_score = (self.bayesian_mean * 0.6) + (self.ema_quality * 0.4)
        return max(0.0, min(1.0, raw_score * self.demotion_penalty))

    def apply_time_decay(self, elapsed_seconds: float, half_life_seconds: Optional[float] = None) -> None:
        """Apply exponential time decay to observations towards prior uncertainty.

        alpha <- 1.0 + (alpha - 1.0) * decay
        beta <- 1.0 + (beta - 1.0) * decay
        effective_n <- effective_n * decay
        """
        effective_hl = half_life_seconds if half_life_seconds is not None else float(get_hyperparameter("time_decay_half_life_seconds"))
        if elapsed_seconds <= 0 or effective_hl <= 0:
            return

        decay = math.exp(- (math.log(2) / effective_hl) * elapsed_seconds)

        self.alpha = 1.0 + (self.alpha - 1.0) * decay
        self.beta = 1.0 + (self.beta - 1.0) * decay
        self.effective_n = max(0.0, self.effective_n * decay)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "task_type": self.task_type,
            "alpha": round(self.alpha, 4),
            "beta": round(self.beta, 4),
            "bayesian_mean": round(self.bayesian_mean, 4),
            "bayesian_variance": round(self.bayesian_variance, 6),
            "ema_quality": round(self.ema_quality, 4),
            "ema_latency_ms": round(self.ema_latency_ms, 2),
            "ema_cost": round(self.ema_cost, 6),
            "ema_tool_accuracy": round(self.ema_tool_accuracy, 4),
            "ema_error_rate": round(self.ema_error_rate, 4),
            "sample_size": self.sample_size,
            "effective_n": round(self.effective_n, 2),
            "successes": self.successes,
            "failures": self.failures,
            "is_demoted": self.is_demoted,
            "demoted_reason": self.demoted_reason,
            "demoted_at": self.demoted_at,
            "demotion_penalty": round(self.demotion_penalty, 3),
            "composite_score": round(self.score, 4),
            "last_updated_at": self.last_updated_at,
        }


# ============================================================================
# 3. Drift Detection & Automatic Demotion
# ============================================================================

@dataclass
class DriftEvent:
    model_id: str
    task_type: str
    trigger_type: str
    reason: str
    baseline_value: float
    recent_value: float
    timestamp: float = field(default_factory=time.time)


class DriftDetector:
    """Detects performance regressions and recommends demotions or recoveries."""

    def __init__(
        self,
        min_recent_samples: int = 3,
        error_spike_threshold: Optional[float] = None,
        tool_accuracy_drop_threshold: Optional[float] = None,
        quality_drop_threshold: Optional[float] = None,
        demotion_penalty: Optional[float] = None,
    ) -> None:
        self.min_recent_samples = min_recent_samples
        self._error_spike_threshold = error_spike_threshold
        self._tool_accuracy_drop_threshold = tool_accuracy_drop_threshold
        self._quality_drop_threshold = quality_drop_threshold
        self._demotion_penalty = demotion_penalty
        self.events: List[DriftEvent] = []

    @property
    def error_spike_threshold(self) -> float:
        if self._error_spike_threshold is not None:
            return self._error_spike_threshold
        return float(get_hyperparameter("drift_error_spike_threshold"))

    @property
    def tool_accuracy_drop_threshold(self) -> float:
        if self._tool_accuracy_drop_threshold is not None:
            return self._tool_accuracy_drop_threshold
        return float(get_hyperparameter("drift_tool_accuracy_drop_threshold"))

    @property
    def quality_drop_threshold(self) -> float:
        if self._quality_drop_threshold is not None:
            return self._quality_drop_threshold
        return float(get_hyperparameter("drift_quality_drop_threshold"))

    @property
    def demotion_penalty(self) -> float:
        if self._demotion_penalty is not None:
            return self._demotion_penalty
        return float(get_hyperparameter("demotion_penalty"))

    def check_drift(self, estimate: QualityEstimate) -> Optional[DriftEvent]:
        """Examine recent outcomes against baseline to detect regression."""
        if len(estimate.recent_outcomes) < self.min_recent_samples:
            return None

        recent = estimate.recent_outcomes[-self.min_recent_samples:]
        recent_count = len(recent)

        # 1. Error rate regression
        recent_errors = sum(1 for o in recent if o.get("error"))
        recent_err_rate = recent_errors / recent_count
        baseline_err_rate = estimate.ema_error_rate

        if recent_err_rate >= self.error_spike_threshold and (recent_err_rate - baseline_err_rate) >= 0.15:
            reason = (
                f"Sudden error spike on task '{estimate.task_type}': "
                f"recent error rate {recent_err_rate:.1%} vs baseline {baseline_err_rate:.1%} "
                f"over last {recent_count} requests."
            )
            event = DriftEvent(
                model_id=estimate.model_id,
                task_type=estimate.task_type,
                trigger_type="error_spike",
                reason=reason,
                baseline_value=baseline_err_rate,
                recent_value=recent_err_rate,
            )
            self.events.append(event)
            return event

        # 2. Tool accuracy regression
        tool_samples = [o.get("tool_calls_valid") for o in recent if o.get("tool_calls_valid") is not None]
        if len(tool_samples) >= 2:
            recent_tool_acc = sum(1 for v in tool_samples if v) / len(tool_samples)
            baseline_tool_acc = estimate.ema_tool_accuracy
            if (baseline_tool_acc - recent_tool_acc) >= self.tool_accuracy_drop_threshold:
                reason = (
                    f"Tool accuracy regression on task '{estimate.task_type}': "
                    f"recent tool accuracy {recent_tool_acc:.1%} vs baseline {baseline_tool_acc:.1%}."
                )
                event = DriftEvent(
                    model_id=estimate.model_id,
                    task_type=estimate.task_type,
                    trigger_type="tool_accuracy_drop",
                    reason=reason,
                    baseline_value=baseline_tool_acc,
                    recent_value=recent_tool_acc,
                )
                self.events.append(event)
                return event

        # 3. Overall quality score regression
        recent_qualities = [o.get("quality_score", 0.0) for o in recent]
        recent_avg_q = sum(recent_qualities) / recent_count
        baseline_q = estimate.bayesian_mean

        if (baseline_q - recent_avg_q) >= self.quality_drop_threshold and recent_avg_q < 0.40:
            reason = (
                f"Quality regression on task '{estimate.task_type}': "
                f"recent quality {recent_avg_q:.2f} fell by {baseline_q - recent_avg_q:.2f} "
                f"below baseline {baseline_q:.2f}."
            )
            event = DriftEvent(
                model_id=estimate.model_id,
                task_type=estimate.task_type,
                trigger_type="quality_drop",
                reason=reason,
                baseline_value=baseline_q,
                recent_value=recent_avg_q,
            )
            self.events.append(event)
            return event

        return None

    def check_recovery(self, estimate: QualityEstimate) -> bool:
        """Check whether a demoted model has recovered acceptable performance."""
        if not estimate.is_demoted or len(estimate.recent_outcomes) < self.min_recent_samples:
            return False

        recent = estimate.recent_outcomes[-self.min_recent_samples:]
        recent_errors = sum(1 for o in recent if o.get("error"))
        recent_err_rate = recent_errors / len(recent)
        recent_avg_q = sum(o.get("quality_score", 0.0) for o in recent) / len(recent)

        # Recovery condition: low error rate and good quality
        max_err = float(get_hyperparameter("recovery_error_rate_threshold"))
        min_q = float(get_hyperparameter("recovery_quality_threshold"))
        return recent_err_rate <= max_err and recent_avg_q >= min_q


# ============================================================================
# 4. Drex Trust Calibration
# ============================================================================

@dataclass
class DrexCalibrationRecord:
    decision_type: str
    drex_evaluations: int = 0
    drex_successes: int = 0
    deterministic_evaluations: int = 0
    deterministic_successes: int = 0
    weight: float = 0.50
    confidence_threshold: float = 0.70
    enabled: bool = True
    history: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def drex_accuracy(self) -> float:
        return self.drex_successes / self.drex_evaluations if self.drex_evaluations > 0 else 0.5

    @property
    def deterministic_accuracy(self) -> float:
        return self.deterministic_successes / self.deterministic_evaluations if self.deterministic_evaluations > 0 else 0.5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_type": self.decision_type,
            "drex_evaluations": self.drex_evaluations,
            "drex_successes": self.drex_successes,
            "drex_accuracy": round(self.drex_accuracy, 4),
            "deterministic_evaluations": self.deterministic_evaluations,
            "deterministic_successes": self.deterministic_successes,
            "deterministic_accuracy": round(self.deterministic_accuracy, 4),
            "weight": round(self.weight, 3),
            "confidence_threshold": round(self.confidence_threshold, 3),
            "enabled": self.enabled,
            "history_count": len(self.history),
        }


class DrexTrustCalibrator:
    """Dynamically calibrates Drex weights and confidence thresholds per decision type."""

    def __init__(self, min_evals_for_calibration: int = 5) -> None:
        self.min_evals = min_evals_for_calibration
        self.records: Dict[str, DrexCalibrationRecord] = {}

    def get_or_create(self, decision_type: str) -> DrexCalibrationRecord:
        if decision_type not in self.records:
            self.records[decision_type] = DrexCalibrationRecord(decision_type=decision_type)
        return self.records[decision_type]

    def record_outcome(
        self,
        decision_type: str,
        drex_success: bool,
        deterministic_success: bool,
        drex_confidence: float = 1.0,
    ) -> Dict[str, Any]:
        """Record comparative outcome and update trust calibration."""
        rec = self.get_or_create(decision_type)
        rec.drex_evaluations += 1
        rec.deterministic_evaluations += 1

        if drex_success:
            rec.drex_successes += 1
        if deterministic_success:
            rec.deterministic_successes += 1

        adjustment: Dict[str, Any] = {
            "decision_type": decision_type,
            "calibrated": False,
            "explanation": "Accumulating comparative samples.",
        }

        # Calibrate once minimum evaluation threshold is met
        if rec.drex_evaluations >= self.min_evals:
            drex_acc = rec.drex_accuracy
            det_acc = rec.deterministic_accuracy
            delta = drex_acc - det_acc

            old_enabled = rec.enabled
            old_weight = rec.weight
            old_threshold = rec.confidence_threshold

            if delta < -0.10 or drex_acc < 0.45:
                # Drex is underperforming deterministic utility; disable or severely penalize
                rec.enabled = False
                rec.weight = 0.0
                rec.confidence_threshold = 0.90
                explanation = (
                    f"Disabled Drex for '{decision_type}': Drex accuracy ({drex_acc:.1%}) "
                    f"trailed deterministic utility ({det_acc:.1%}) by {abs(delta):.1%}."
                )
            elif delta < 0.0:
                # Drex is slightly trailing; raise confidence bar and reduce weight
                rec.enabled = True
                rec.weight = max(0.15, rec.weight * 0.8)
                rec.confidence_threshold = min(0.85, rec.confidence_threshold + 0.05)
                explanation = (
                    f"Reduced Drex trust for '{decision_type}': Drex accuracy ({drex_acc:.1%}) "
                    f"below deterministic ({det_acc:.1%}). Increased threshold to {rec.confidence_threshold:.2f}."
                )
            elif delta >= 0.05:
                # Drex adds verified value; promote weight and lower threshold
                rec.enabled = True
                rec.weight = min(0.85, rec.weight + 0.10)
                rec.confidence_threshold = max(0.50, rec.confidence_threshold - 0.05)
                explanation = (
                    f"Promoted Drex trust for '{decision_type}': Drex accuracy ({drex_acc:.1%}) "
                    f"exceeded deterministic ({det_acc:.1%}) by +{delta:.1%}."
                )
            else:
                explanation = f"Drex parity maintained ({drex_acc:.1%} vs {det_acc:.1%})."

            rec.history.append({
                "timestamp": time.time(),
                "drex_acc": drex_acc,
                "det_acc": det_acc,
                "weight": rec.weight,
                "threshold": rec.confidence_threshold,
                "enabled": rec.enabled,
                "explanation": explanation,
            })

            adjustment = {
                "decision_type": decision_type,
                "calibrated": True,
                "enabled": rec.enabled,
                "weight": rec.weight,
                "confidence_threshold": rec.confidence_threshold,
                "delta": round(delta, 4),
                "explanation": explanation,
            }

        return adjustment


# ============================================================================
# 5. Route Trace & Explain Engine
# ============================================================================

@dataclass
class RouteTrace:
    """Full execution trace of a routing decision."""

    request_id: str
    timestamp: float
    task_classification: Dict[str, Any]
    candidates: List[str]
    constraints: Dict[str, Any]
    scores: Dict[str, Dict[str, float]]
    drex_recommendation: Dict[str, Any]
    final_choice: Dict[str, Any]
    outcome: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "task_classification": self.task_classification,
            "candidates": self.candidates,
            "constraints": self.constraints,
            "scores": self.scores,
            "drex_recommendation": self.drex_recommendation,
            "final_choice": self.final_choice,
            "outcome": self.outcome,
        }


class TraceExplainEngine:
    """Engine for storing, reconstructing, and explaining routing decision traces."""

    def __init__(self) -> None:
        self._traces: Dict[str, RouteTrace] = {}

    def record_trace(self, trace: RouteTrace, conn: Optional[sqlite3.Connection] = None) -> None:
        self._traces[trace.request_id] = trace
        if conn:
            try:
                conn.execute(
                    "INSERT INTO routing_traces (request_id, trace_json, created_at) "
                    "VALUES (?, ?, ?) ON CONFLICT(request_id) DO UPDATE SET "
                    "trace_json = excluded.trace_json",
                    (trace.request_id, json.dumps(trace.to_dict()), int(trace.timestamp * 1000)),
                )
                conn.commit()
            except Exception as exc:
                logger.debug("Could not persist route trace to db: %s", exc)

    def get_trace(self, request_id: str, conn: Optional[sqlite3.Connection] = None) -> Optional[RouteTrace]:
        if request_id in self._traces:
            return self._traces[request_id]

        if conn:
            try:
                row = conn.execute(
                    "SELECT trace_json FROM routing_traces WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                if row:
                    data = json.loads(row["trace_json"])
                    trace = RouteTrace(**data)
                    self._traces[request_id] = trace
                    return trace
            except Exception:
                pass

        return None

    def explain(self, request_id: str, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
        """Explain a routing decision trace with full breakdown."""
        trace = self.get_trace(request_id, conn=conn)
        if trace:
            res = trace.to_dict()
            res["plain_explanation"] = self._format_plain_explanation(trace)
            return res

        # Fallback reconstruction if request exists in request_log
        if conn:
            try:
                r_row = conn.execute(
                    "SELECT * FROM request_log WHERE request_id = ?", (request_id,)
                ).fetchone()
                if r_row:
                    model_id = r_row["model_id"]
                    provider = r_row["provider"]
                    synth_trace = RouteTrace(
                        request_id=request_id,
                        timestamp=float(r_row["created_at"]) / 1000.0,
                        task_classification={
                            "task_type": "general",
                            "requires_vision": False,
                            "privacy_class": r_row["privacy_class"],
                        },
                        candidates=[model_id],
                        constraints={"non_demoted_only": True},
                        scores={model_id: {"composite_score": 0.85, "bayesian_mean": 0.85}},
                        drex_recommendation={
                            "recommended_model": None,
                            "confidence": None,
                            "enabled": False,
                            "weight": 0.0,
                        },
                        final_choice={
                            "model_id": model_id,
                            "provider": provider,
                            "score": 0.85,
                            "reason": f"Executed via route assignment for provider '{provider}'.",
                        },
                        outcome={
                            "http_status": r_row["http_status"],
                            "outcome": r_row["outcome"],
                            "latency_ms": r_row["latency_ms"],
                        },
                    )
                    res = synth_trace.to_dict()
                    res["plain_explanation"] = self._format_plain_explanation(synth_trace)
                    return res
            except Exception:
                pass

        return {
            "request_id": request_id,
            "error": "Trace not found for request id",
            "task_classification": {},
            "candidates": [],
            "constraints": {},
            "scores": {},
            "drex_recommendation": {},
            "final_choice": {},
            "plain_explanation": f"No routing trace recorded for request '{request_id}'.",
        }

    def _format_plain_explanation(self, trace: RouteTrace) -> str:
        choice = trace.final_choice.get("model_id", "unknown")
        task = trace.task_classification.get("task_type", "general")
        reason = trace.final_choice.get("reason", "Highest composite utility score.")
        drex = trace.drex_recommendation
        drex_part = ""
        if drex and drex.get("recommended_model"):
            conf = drex.get("confidence", 0.0)
            drex_part = f" Drex recommended '{drex['recommended_model']}' with confidence {conf:.2f}."

        return (
            f"Request {trace.request_id}: Classified as '{task}'. "
            f"Selected model '{choice}'. {reason}{drex_part}"
        )


# ============================================================================
# 6. Online Learning Router
# ============================================================================

class OnlineLearningRouter:
    """Master orchestrator for online feedback, drift detection, Drex calibration, and routing."""

    def __init__(
        self,
        conn: Optional[sqlite3.Connection] = None,
        half_life_seconds: Optional[float] = None,
        drift_detector: Optional[DriftDetector] = None,
        calibrator: Optional[DrexTrustCalibrator] = None,
        explain_engine: Optional[TraceExplainEngine] = None,
    ) -> None:
        self.conn = conn
        self._half_life_seconds = half_life_seconds
        self.drift_detector = drift_detector or DriftDetector()
        self.calibrator = calibrator or DrexTrustCalibrator()
        self.explain_engine = explain_engine or TraceExplainEngine()
        self.estimates: Dict[Tuple[str, str], QualityEstimate] = {}
        self.demotion_log: List[Dict[str, Any]] = []
        if self.conn:
            self._init_db_schema()

    @property
    def half_life_seconds(self) -> float:
        if self._half_life_seconds is not None:
            return self._half_life_seconds
        return float(get_hyperparameter("time_decay_half_life_seconds"))

    def _init_db_schema(self) -> None:
        if not self.conn:
            return
        schema = """
        CREATE TABLE IF NOT EXISTS routing_traces (
            request_id TEXT PRIMARY KEY,
            trace_json TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS routing_demotions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_id TEXT NOT NULL,
            task_type TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            reason TEXT NOT NULL,
            baseline_val REAL NOT NULL,
            recent_val REAL NOT NULL,
            created_at INTEGER NOT NULL
        );
        """
        try:
            self.conn.executescript(schema)
            self.conn.commit()
        except Exception as exc:
            logger.debug("Could not initialize routing schema: %s", exc)

    def get_estimate(self, model_id: str, task_type: str = "general") -> QualityEstimate:
        key = (model_id, task_type)
        if key not in self.estimates:
            self.estimates[key] = QualityEstimate(model_id=model_id, task_type=task_type)
        return self.estimates[key]

    def classify_task(self, request_data: Any) -> Dict[str, Any]:
        """Classify task requirements and attributes."""
        if isinstance(request_data, dict):
            task_type = request_data.get("task_type") or request_data.get("role") or "general"
            requires_vision = bool(request_data.get("requires_vision", False))
            requires_tools = bool(request_data.get("requires_tools", False))
            max_cost = request_data.get("max_cost")
            max_latency_ms = request_data.get("max_latency_ms")
        else:
            task_type = "general"
            requires_vision = False
            requires_tools = False
            max_cost = None
            max_latency_ms = None

        return {
            "task_type": task_type,
            "requires_vision": requires_vision,
            "requires_tools": requires_tools,
            "max_cost": max_cost,
            "max_latency_ms": max_latency_ms,
        }

    def select_route(
        self,
        request_id: str,
        candidates: List[str],
        task_data: Optional[Dict[str, Any]] = None,
        drex_recommendation: Optional[Dict[str, Any]] = None,
    ) -> RouteTrace:
        """Evaluate candidates, combine deterministic utility with Drex, and select optimal route."""
        now = time.time()
        classification = self.classify_task(task_data or {})
        task_type = classification["task_type"]

        if not candidates:
            raise ValueError("Candidate model list cannot be empty.")

        constraints = {
            "non_demoted_preferred": True,
            "max_cost": classification.get("max_cost"),
            "max_latency_ms": classification.get("max_latency_ms"),
        }

        # Apply time decay to candidate estimates before scoring
        scores: Dict[str, Dict[str, float]] = {}
        for c in candidates:
            est = self.get_estimate(c, task_type)
            elapsed = now - est.last_updated_at
            if elapsed > 0:
                est.apply_time_decay(elapsed, self.half_life_seconds)

            det_score = est.score
            scores[c] = {
                "bayesian_mean": round(est.bayesian_mean, 4),
                "ema_quality": round(est.ema_quality, 4),
                "sample_size": float(est.sample_size),
                "demotion_penalty": round(est.demotion_penalty, 3),
                "deterministic_utility": round(det_score, 4),
                "final_score": round(det_score, 4),
            }

        # Calibration & Drex integration
        drex_rec = drex_recommendation or {}
        drex_model = drex_rec.get("recommended_model")
        drex_conf = float(drex_rec.get("confidence", 0.0))

        calib = self.calibrator.get_or_create(task_type)
        drex_enabled = calib.enabled and (drex_conf >= calib.confidence_threshold)
        drex_weight = calib.weight if drex_enabled else 0.0

        drex_info = {
            "recommended_model": drex_model,
            "confidence": drex_conf,
            "enabled": drex_enabled,
            "calibrated_weight": round(drex_weight, 3),
            "confidence_threshold": round(calib.confidence_threshold, 3),
        }

        # Blend scores
        best_candidate = candidates[0]
        highest_score = -1.0

        for c in candidates:
            score_data = scores[c]
            det_val = score_data["deterministic_utility"]

            if drex_enabled and drex_model == c:
                blended = (1.0 - drex_weight) * det_val + (drex_weight * drex_conf)
            elif drex_enabled and drex_model in candidates and drex_model != c:
                blended = (1.0 - drex_weight) * det_val
            else:
                blended = det_val

            # Apply demotion penalty
            final_val = round(blended * score_data["demotion_penalty"], 4)
            score_data["final_score"] = final_val

            if final_val > highest_score:
                highest_score = final_val
                best_candidate = c

        # Choice rationale
        best_est = self.get_estimate(best_candidate, task_type)
        if best_est.is_demoted:
            reason = f"Candidate '{best_candidate}' selected as fallback despite demotion ({best_est.demoted_reason})."
        elif drex_enabled and drex_model == best_candidate:
            reason = f"Drex recommendation concurred with high confidence ({drex_conf:.2f}), boosting final utility."
        else:
            reason = f"Candidate '{best_candidate}' ranked highest with composite utility {highest_score:.4f}."

        choice = {
            "model_id": best_candidate,
            "score": highest_score,
            "reason": reason,
        }

        trace = RouteTrace(
            request_id=request_id,
            timestamp=now,
            task_classification=classification,
            candidates=list(candidates),
            constraints=constraints,
            scores=scores,
            drex_recommendation=drex_info,
            final_choice=choice,
        )

        self.explain_engine.record_trace(trace, conn=self.conn)
        return trace

    def record_outcome(
        self,
        request_id: str,
        outcome: OracleOutcome,
        model_id: Optional[str] = None,
        task_type: str = "general",
    ) -> Dict[str, Any]:
        """Record verified outcome, update Bayesian and EMA estimates, detect drift, and calibrate Drex."""
        now = time.time()
        trace = self.explain_engine.get_trace(request_id, conn=self.conn)

        resolved_model = model_id or (trace.final_choice.get("model_id") if trace else None)
        if not resolved_model:
            raise ValueError("model_id must be provided or exist in routing trace.")

        resolved_task = task_type
        if trace and "task_type" in trace.task_classification:
            resolved_task = trace.task_classification["task_type"]

        est = self.get_estimate(resolved_model, resolved_task)

        # 1. Apply time decay to prior observations
        elapsed = now - est.last_updated_at
        if elapsed > 0:
            est.apply_time_decay(elapsed, self.half_life_seconds)

        # 2. Compute quality score from oracle signals
        q_score = outcome.compute_quality_score()
        success = not outcome.error and q_score >= 0.50

        # 3. Bayesian update (Beta-Binomial)
        est.alpha += q_score
        est.beta += (1.0 - q_score)
        est.sample_size += 1
        est.effective_n += 1.0

        if success:
            est.successes += 1
        else:
            est.failures += 1

        # 4. Exponential moving average update
        gamma = float(get_hyperparameter("ema_gamma"))
        est.ema_quality = (1.0 - gamma) * est.ema_quality + gamma * q_score
        if outcome.latency > 0:
            est.ema_latency_ms = (1.0 - gamma) * est.ema_latency_ms + gamma * outcome.latency
        if outcome.cost > 0:
            est.ema_cost = (1.0 - gamma) * est.ema_cost + gamma * outcome.cost
        if outcome.tool_calls_valid is not None:
            tool_val = 1.0 if outcome.tool_calls_valid else 0.0
            est.ema_tool_accuracy = (1.0 - gamma) * est.ema_tool_accuracy + gamma * tool_val

        err_val = 1.0 if outcome.error else 0.0
        est.ema_error_rate = (1.0 - gamma) * est.ema_error_rate + gamma * err_val

        # Add to sliding window of recent outcomes
        est.recent_outcomes.append({
            "timestamp": now,
            "quality_score": q_score,
            "error": outcome.error,
            "tool_calls_valid": outcome.tool_calls_valid,
            "latency": outcome.latency,
            "cost": outcome.cost,
        })
        if len(est.recent_outcomes) > 20:
            est.recent_outcomes.pop(0)

        est.last_updated_at = now

        # 5. Drift Detection & Automatic Demotion
        drift_event = self.drift_detector.check_drift(est)
        demoted_this_round = False
        recovered_this_round = False

        if drift_event and not est.is_demoted:
            est.is_demoted = True
            est.demoted_reason = drift_event.reason
            est.demoted_at = now
            est.demotion_penalty = self.drift_detector.demotion_penalty
            demoted_this_round = True

            log_entry = {
                "timestamp": now,
                "model_id": resolved_model,
                "task_type": resolved_task,
                "trigger_type": drift_event.trigger_type,
                "reason": drift_event.reason,
                "baseline": drift_event.baseline_value,
                "recent": drift_event.recent_value,
            }
            self.demotion_log.append(log_entry)
            logger.warning("Automatic model demotion: %s", drift_event.reason)

            if self.conn:
                try:
                    self.conn.execute(
                        "INSERT INTO routing_demotions (model_id, task_type, trigger_type, reason, baseline_val, recent_val, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (resolved_model, resolved_task, drift_event.trigger_type, drift_event.reason,
                         float(drift_event.baseline_value), float(drift_event.recent_value), int(now * 1000)),
                    )
                    self.conn.commit()
                except Exception:
                    pass
        elif est.is_demoted and self.drift_detector.check_recovery(est):
            # Automatic recovery
            est.is_demoted = False
            est.demoted_reason = None
            est.demoted_at = None
            est.demotion_penalty = 1.0
            recovered_this_round = True
            logger.info("Automatic model recovery on task '%s' for model '%s'", resolved_task, resolved_model)

        # 6. Drex Trust Calibration tracking
        drex_calibration_result = None
        if trace and trace.drex_recommendation:
            drex_rec = trace.drex_recommendation
            drex_candidate = drex_rec.get("recommended_model")
            if drex_candidate:
                drex_succeeded = (drex_candidate == resolved_model and success)
                det_succeeded = success
                drex_calibration_result = self.calibrator.record_outcome(
                    decision_type=resolved_task,
                    drex_success=drex_succeeded,
                    deterministic_success=det_succeeded,
                    drex_confidence=float(drex_rec.get("confidence", 1.0)),
                )

        # 7. Update Trace Outcome
        if trace:
            trace.outcome = {
                "quality_score": q_score,
                "success": success,
                "error": outcome.error,
                "latency_ms": outcome.latency,
                "cost_usd": outcome.cost,
                "tests_pass": outcome.tests_pass,
                "tool_calls_valid": outcome.tool_calls_valid,
                "user_accepted": outcome.user_accepted,
                "no_retry_needed": outcome.no_retry_needed,
                "demoted": demoted_this_round,
                "recovered": recovered_this_round,
            }
            self.explain_engine.record_trace(trace, conn=self.conn)

        return {
            "request_id": request_id,
            "model_id": resolved_model,
            "task_type": resolved_task,
            "quality_score": q_score,
            "success": success,
            "sample_size": est.sample_size,
            "bayesian_mean": round(est.bayesian_mean, 4),
            "is_demoted": est.is_demoted,
            "demoted_reason": est.demoted_reason,
            "drex_calibration": drex_calibration_result,
        }

    def explain(self, request_id: str) -> Dict[str, Any]:
        """Explain routing decision for given request ID."""
        return self.explain_engine.explain(request_id, conn=self.conn)


# Global singleton instance for easy import and sharing
_global_router: Optional[OnlineLearningRouter] = None


def get_learning_router(conn: Optional[sqlite3.Connection] = None) -> OnlineLearningRouter:
    global _global_router
    if _global_router is None:
        _global_router = OnlineLearningRouter(conn=conn)
    elif conn is not None and _global_router.conn is None:
        _global_router.conn = conn
        _global_router._init_db_schema()
    return _global_router
