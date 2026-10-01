"""
brain/guard/stuck_detector.py
Port of the 5-pattern stuck detection algorithm from OpenHands SDK.
Original source: openhands-sdk/openhands/sdk/conversation/stuck_detector.py (MIT License)
Algorithm ported without copying code — reimplemented from documented spec.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class StuckResult:
    is_stuck: bool
    pattern: Optional[str]  # none | repeating_action_observation | repeating_action_error | monologue | pingpong
    iteration: int
    nudge: Optional[str]


# ---------------------------------------------------------------------------
# StuckDetector
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', re.IGNORECASE)
_TIMESTAMP_RE = re.compile(r'\b\d{10,13}\b')


class StuckDetector:
    """Deterministic loop/stuck detector operating on a sliding window of events.

    Detects four patterns:
    1. repeating_action_observation — same (action, observation) pair repeated ≥4 times
    2. repeating_action_error       — same error event repeated ≥3 times consecutively
    3. monologue                    — ≥3 consecutive message events with no tool use
    4. pingpong                     — A→B→A→B alternation ≥6 events (i.e. 3 full cycles)
    """

    WINDOW: int = 20
    REPEAT_ACTION_THRESHOLD: int = 4
    REPEAT_ERROR_THRESHOLD: int = 3
    MONOLOGUE_THRESHOLD: int = 3
    PINGPONG_THRESHOLD: int = 6

    def __init__(self) -> None:
        self._events: deque[dict] = deque(maxlen=self.WINDOW)
        self._iteration: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_event(self, event: dict) -> None:
        """Append an event to the internal sliding window."""
        self._events.append(event)
        self._iteration += 1

    def check(self) -> StuckResult:
        """Evaluate the current event window and return a StuckResult."""
        pattern: Optional[str] = None

        if self._check_repeating_action_observation():
            pattern = "repeating_action_observation"
        elif self._check_repeating_action_error():
            pattern = "repeating_action_error"
        elif self._check_repeating_action_only():
            pattern = "repeating_action_observation"
        elif self._check_monologue():
            pattern = "monologue"
        elif self._check_pingpong():
            pattern = "pingpong"

        is_stuck = pattern is not None
        nudge = self._generate_nudge(pattern) if is_stuck else None

        return StuckResult(
            is_stuck=is_stuck,
            pattern=pattern,
            iteration=self._iteration,
            nudge=nudge,
        )

    # ------------------------------------------------------------------
    # Event fingerprinting
    # ------------------------------------------------------------------

    def _event_key(self, event: dict) -> str:
        """Produce a structural fingerprint of an event, stripping ephemeral fields."""
        import json

        def _clean(obj):
            """Recursively strip UUID/timestamp values but preserve structure."""
            if isinstance(obj, dict):
                cleaned = {}
                for k, v in obj.items():
                    # Drop top-level ephemeral keys
                    if k in ("id", "timestamp", "created_at", "request_id", "message_id", "session_id"):
                        continue
                    cleaned[k] = _clean(v)
                return cleaned
            elif isinstance(obj, list):
                return [_clean(i) for i in obj]
            elif isinstance(obj, str):
                # Strip UUIDs and numeric timestamps from string values
                val = _UUID_RE.sub("<uuid>", obj)
                val = _TIMESTAMP_RE.sub("<ts>", val)
                return val
            return obj

        cleaned = _clean(event)
        return json.dumps(cleaned, sort_keys=True, separators=(",", ":"))

    # ------------------------------------------------------------------
    # Pattern checks
    # ------------------------------------------------------------------

    def _check_repeating_action_observation(self) -> bool:
        """True if the same (action, observation) pair appears ≥ REPEAT_ACTION_THRESHOLD times."""
        events = list(self._events)
        if len(events) < self.REPEAT_ACTION_THRESHOLD * 2:
            return False

        # Walk through action/observation pairs at the tail of the window
        pairs: list[tuple[str, str]] = []
        i = 0
        while i < len(events) - 1:
            e1 = events[i]
            e2 = events[i + 1]
            t1 = e1.get("type", "")
            t2 = e2.get("type", "")
            if t1 == "action" and t2 == "observation":
                pairs.append((self._event_key(e1), self._event_key(e2)))
                i += 2
            else:
                i += 1

        if len(pairs) < self.REPEAT_ACTION_THRESHOLD:
            return False

        # Check the last REPEAT_ACTION_THRESHOLD pairs are identical
        tail = pairs[-self.REPEAT_ACTION_THRESHOLD:]
        return len(set(k1 + k2 for k1, k2 in tail)) == 1

    def _check_repeating_action_only(self) -> bool:
        """True if ≥ REPEAT_ACTION_THRESHOLD consecutive action events are identical.

        Claude Code emits PreToolUse hooks as standalone action events (no paired
        observation in the window), so a pure-action repeat must also be caught.
        """
        events = list(self._events)
        if len(events) < self.REPEAT_ACTION_THRESHOLD:
            return False

        tail = events[-self.REPEAT_ACTION_THRESHOLD:]
        if not all(e.get("type") == "action" for e in tail):
            return False

        keys = [self._event_key(e) for e in tail]
        return len(set(keys)) == 1

    def _check_repeating_action_error(self) -> bool:
        """True if ≥ REPEAT_ERROR_THRESHOLD consecutive error events are identical."""
        events = list(self._events)
        if len(events) < self.REPEAT_ERROR_THRESHOLD:
            return False

        tail = events[-self.REPEAT_ERROR_THRESHOLD:]
        if not all(e.get("type") == "error" for e in tail):
            return False

        keys = [self._event_key(e) for e in tail]
        return len(set(keys)) == 1

    def _check_monologue(self) -> bool:
        """True if the last ≥ MONOLOGUE_THRESHOLD events are message events with no tool use."""
        events = list(self._events)
        if len(events) < self.MONOLOGUE_THRESHOLD:
            return False

        tail = events[-self.MONOLOGUE_THRESHOLD:]
        return all(
            e.get("type") == "message" and not e.get("tool_name") and not e.get("tool_use")
            for e in tail
        )

    def _check_pingpong(self) -> bool:
        """True if the last PINGPONG_THRESHOLD events alternate between exactly 2 distinct keys."""
        events = list(self._events)
        if len(events) < self.PINGPONG_THRESHOLD:
            return False

        tail = events[-self.PINGPONG_THRESHOLD:]
        keys = [self._event_key(e) for e in tail]

        distinct = set(keys)
        if len(distinct) != 2:
            return False

        # Must strictly alternate: A B A B A B ...
        key_a, key_b = tuple(distinct)
        for idx, k in enumerate(keys):
            expected = key_a if idx % 2 == 0 else key_b
            alt_expected = key_b if idx % 2 == 0 else key_a
            if k != expected and k != alt_expected:
                return False
            # Enforce alternation
            if idx > 0 and k == keys[idx - 1]:
                return False

        return True

    # ------------------------------------------------------------------
    # Nudge generation
    # ------------------------------------------------------------------

    def _generate_nudge(self, pattern: Optional[str]) -> Optional[str]:
        """Return a corrective prompt injection for the detected pattern."""
        nudges = {
            "repeating_action_observation": (
                "⚠️ Loop detected: you are repeating the same action-observation cycle. "
                "Try a different approach, use a different tool, or re-examine your assumptions."
            ),
            "repeating_action_error": (
                "⚠️ Repeated error detected: the same tool invocation keeps failing. "
                "Stop retrying. Diagnose the root cause, adjust parameters, or choose an alternative strategy."
            ),
            "monologue": (
                "⚠️ Monologue detected: you are generating messages without taking any tool actions. "
                "Take a concrete action or ask the user for clarification."
            ),
            "pingpong": (
                "⚠️ Ping-pong detected: you are oscillating between two states without making progress. "
                "Break the cycle — re-read the requirements, form a new plan, and commit to it."
            ),
        }
        return nudges.get(pattern) if pattern else None
