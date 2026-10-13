"""brain/routing/escalation.py — Failure validation and state-preserving route escalation.

Enables the router to try the cheapest viable route first, and upon validated
failure (invalid tool call, refusal, test failure, timeout, 429), escalate to a
stronger route without corrupting caller session state.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional, Set
from pydantic import BaseModel, Field

from brain.routing.scorer import ScoredCandidate


class FailureType(str, Enum):
    INVALID_TOOL_CALL = "invalid_tool_call"
    REFUSAL = "refusal"
    TEST_FAILURE = "test_failure"
    TIMEOUT = "timeout"
    RATE_LIMIT_429 = "rate_limit_429"
    PROVIDER_5XX = "provider_5xx"
    UNKNOWN = "unknown"


class EscalationEvent(BaseModel):
    session_id: str
    attempt_index: int
    failed_route_id: str
    failure_type: FailureType
    new_route_id: str
    reason: str
    state_preserved: bool = True


class EscalationManager:
    """Manages multi-attempt escalation chains without corrupting conversation state."""

    def __init__(self) -> None:
        # session_id -> list of failed route_ids
        self._session_failed_routes: Dict[str, Set[str]] = {}
        # session_id -> list of escalation events
        self._session_events: Dict[str, List[EscalationEvent]] = {}

    def get_failed_routes(self, session_id: str) -> Set[str]:
        return self._session_failed_routes.get(session_id, set())

    def record_failure(
        self,
        session_id: str,
        failed_route_id: str,
        failure_type: FailureType,
    ) -> None:
        if session_id not in self._session_failed_routes:
            self._session_failed_routes[session_id] = set()
        self._session_failed_routes[session_id].add(failed_route_id)

    def select_escalation_candidate(
        self,
        session_id: str,
        failed_route_id: str,
        failure_type: FailureType,
        available_candidates: List[ScoredCandidate],
    ) -> Optional[ScoredCandidate]:
        self.record_failure(session_id, failed_route_id, failure_type)
        failed_set = self.get_failed_routes(session_id)

        # Locate metrics of the failed candidate if present
        failed_cand: Optional[ScoredCandidate] = None
        for c in available_candidates:
            if c.metrics.route_id == failed_route_id:
                failed_cand = c
                break

        # Filter out all routes that previously failed in this session
        eligible = [c for c in available_candidates if c.metrics.route_id not in failed_set]
        if not eligible:
            return None

        # For structural quality failures (invalid tool call or test failure),
        # prioritize strictly stronger models with higher quality
        if failure_type in (FailureType.INVALID_TOOL_CALL, FailureType.TEST_FAILURE) and failed_cand:
            higher_quality = [
                c for c in eligible if c.quality_score > failed_cand.quality_score
            ]
            if higher_quality:
                higher_quality.sort(key=lambda c: (c.quality_score, c.utility_score), reverse=True)
                selected = higher_quality[0]
                self._record_event(session_id, failed_route_id, failure_type, selected.metrics.route_id, "Higher quality route required")
                return selected

        # For timeouts, rate limits, or refusals, pick highest utility among remaining
        eligible.sort(key=lambda c: c.utility_score, reverse=True)
        selected = eligible[0]
        self._record_event(session_id, failed_route_id, failure_type, selected.metrics.route_id, f"Escalated following {failure_type.value}")
        return selected

    def _record_event(
        self,
        session_id: str,
        failed_route_id: str,
        failure_type: FailureType,
        new_route_id: str,
        reason: str,
    ) -> None:
        if session_id not in self._session_events:
            self._session_events[session_id] = []
        attempt_idx = len(self._session_events[session_id]) + 1
        event = EscalationEvent(
            session_id=session_id,
            attempt_index=attempt_idx,
            failed_route_id=failed_route_id,
            failure_type=failure_type,
            new_route_id=new_route_id,
            reason=reason,
            state_preserved=True,
        )
        self._session_events[session_id].append(event)

    def get_escalation_history(self, session_id: str) -> List[EscalationEvent]:
        return list(self._session_events.get(session_id, []))

    def build_fallback_chain(
        self,
        primary_route_id: str,
        candidates: List[ScoredCandidate],
    ) -> List[str]:
        chain = []
        for c in candidates:
            if c.metrics.route_id != primary_route_id and c.metrics.route_id not in chain:
                chain.append(c.metrics.route_id)
        return chain
