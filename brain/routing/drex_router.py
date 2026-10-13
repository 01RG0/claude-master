"""brain/routing/drex_router.py — Decision Taker adjudication for borderline routing.

Queries Drex on top candidates when utility scores are close (borderline),
falling back to the deterministic scorer when Drex is unreachable, over budget,
or below confidence thresholds.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from brain.routing.scorer import ScoredCandidate
from brain.judge.decision_taker import DecisionTaker
from brain.routing.hyperparameters import get_hyperparameter


class DrexRoutingResult(BaseModel):
    selected: ScoredCandidate
    source: str = "deterministic"  # "drex" | "deterministic" | "drex_fallback"
    confidence: Optional[float] = None
    reason: str = ""
    is_borderline: bool = False
    delta_score: float = 0.0


class DrexRouter:
    """Invokes Drex for borderline routing decisions between top candidates."""

    def __init__(
        self,
        decision_taker: Optional[DecisionTaker] = None,
        borderline_margin: Optional[float] = None,
        confidence_threshold: Optional[float] = None,
        high_complexity_margin_multiplier: Optional[float] = None,
        enabled: bool = True,
    ) -> None:
        self.decision_taker = decision_taker or DecisionTaker()
        self._borderline_margin = borderline_margin
        self._confidence_threshold = confidence_threshold
        self._high_complexity_margin_multiplier = high_complexity_margin_multiplier
        self.enabled = enabled

    @property
    def borderline_margin(self) -> float:
        if self._borderline_margin is not None:
            return self._borderline_margin
        return float(get_hyperparameter("borderline_margin"))

    @property
    def confidence_threshold(self) -> float:
        if self._confidence_threshold is not None:
            return self._confidence_threshold
        return float(get_hyperparameter("drex_confidence_threshold"))

    @property
    def high_complexity_margin_multiplier(self) -> float:
        if self._high_complexity_margin_multiplier is not None:
            return self._high_complexity_margin_multiplier
        return float(get_hyperparameter("high_complexity_margin_multiplier"))

    def is_borderline_decision(
        self,
        top_candidates: List[ScoredCandidate],
        complexity: str = "medium",
    ) -> tuple[bool, float]:
        if len(top_candidates) < 2:
            return False, 0.0

        delta = round(top_candidates[0].utility_score - top_candidates[1].utility_score, 4)
        margin = self.borderline_margin * self.high_complexity_margin_multiplier if complexity == "high" else self.borderline_margin
        is_borderline = delta <= margin
        return is_borderline, delta

    def decide(
        self,
        top_candidates: List[ScoredCandidate],
        task_summary: str,
        complexity: str = "medium",
    ) -> DrexRoutingResult:
        if not top_candidates:
            raise ValueError("No candidates provided for routing decision")

        if len(top_candidates) == 1 or not self.enabled:
            return DrexRoutingResult(
                selected=top_candidates[0],
                source="deterministic",
                confidence=top_candidates[0].confidence,
                reason="Single candidate or Drex disabled",
                is_borderline=False,
                delta_score=0.0,
            )

        is_borderline, delta = self.is_borderline_decision(top_candidates, complexity=complexity)
        if not is_borderline:
            return DrexRoutingResult(
                selected=top_candidates[0],
                source="deterministic",
                confidence=top_candidates[0].confidence,
                reason=f"Decisive utility margin ({delta:.4f} > {self.borderline_margin})",
                is_borderline=False,
                delta_score=delta,
            )

        # Build candidate choices for Drex (top 2 to 4 candidates)
        candidates_to_eval = top_candidates[:4]
        candidate_map: Dict[str, ScoredCandidate] = {
            c.metrics.route_id: c for c in candidates_to_eval
        }
        criteria = {
            c.metrics.route_id: (
                f"Utility: {c.utility_score:.2f}, Quality: {c.quality_score:.2f}, "
                f"TTFT: {c.metrics.measured_ttft_ms:.0f}ms, Cost: ${c.estimated_cost_usd:.4f}"
            )
            for c in candidates_to_eval
        }

        eval_state = (
            f"Task: {task_summary}\n"
            f"Complexity: {complexity}\n"
            f"Candidates under borderline evaluation:\n"
            + "\n".join(f"- {rid}: {desc}" for rid, desc in criteria.items())
        )

        try:
            decision = self.decision_taker.decide_provider(
                request_summary=eval_state,
                candidates=list(criteria.keys()),
            )
            # Check source and confidence
            if decision.source == "drex" and decision.value in candidate_map:
                conf = decision.confidence or 0.0
                if conf >= self.confidence_threshold:
                    return DrexRoutingResult(
                        selected=candidate_map[decision.value],
                        source="drex",
                        confidence=conf,
                        reason=f"Drex chose {decision.value} with confidence {conf:.2f}",
                        is_borderline=True,
                        delta_score=delta,
                    )
                else:
                    return DrexRoutingResult(
                        selected=top_candidates[0],
                        source="drex_fallback",
                        confidence=conf,
                        reason=f"Drex confidence {conf:.2f} below threshold {self.confidence_threshold:.2f}; fallback to top scorer",
                        is_borderline=True,
                        delta_score=delta,
                    )
            else:
                return DrexRoutingResult(
                    selected=top_candidates[0],
                    source="deterministic",
                    confidence=top_candidates[0].confidence,
                    reason=f"Drex returned {decision.source}; fallback to top scorer",
                    is_borderline=True,
                    delta_score=delta,
                )
        except Exception as e:
            return DrexRoutingResult(
                selected=top_candidates[0],
                source="deterministic",
                confidence=top_candidates[0].confidence,
                reason=f"Drex evaluation exception ({e}); fallback to top scorer",
                is_borderline=True,
                delta_score=delta,
            )
