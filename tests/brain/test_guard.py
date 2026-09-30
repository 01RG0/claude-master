"""
tests/brain/test_guard.py
Test suite for brain/guard/ — StuckDetector, ContextBuilder, and socket helpers.
Run: python3 -m pytest tests/brain/test_guard.py -v
"""

from __future__ import annotations

import sys
import os

# Ensure repo root is on the path when running from any directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from brain.guard.stuck_detector import StuckDetector, StuckResult
from brain.guard.context_builder import ContextBuilder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _action(name: str = "bash", args: str = "ls", uid: str = "fixed") -> dict:
    return {"type": "action", "action": name, "args": args, "id": uid}


def _observation(content: str = "output", uid: str = "fixed") -> dict:
    return {"type": "observation", "content": content, "id": uid}


def _error(msg: str = "command failed", uid: str = "fixed") -> dict:
    return {"type": "error", "message": msg, "id": uid}


def _message(text: str = "thinking...", uid: str = "fixed") -> dict:
    return {"type": "message", "text": text, "id": uid}


# ---------------------------------------------------------------------------
# StuckDetector tests
# ---------------------------------------------------------------------------


class TestStuckDetectorRepeatingActionObservation:
    def test_stuck_repeating_action_observation(self):
        """4 identical action+observation pairs → is_stuck=True, pattern=repeating_action_observation."""
        det = StuckDetector()
        for _ in range(StuckDetector.REPEAT_ACTION_THRESHOLD):
            det.add_event(_action("bash", "ls /foo", uid="aaa"))
            det.add_event(_observation("No such file", uid="bbb"))
        result = det.check()
        assert result.is_stuck is True
        assert result.pattern == "repeating_action_observation"
        assert result.nudge is not None

    def test_not_stuck_with_varied_action_observation(self):
        """Varied pairs should not trigger repeating_action_observation."""
        det = StuckDetector()
        for i in range(StuckDetector.REPEAT_ACTION_THRESHOLD):
            det.add_event(_action("bash", f"ls /foo/{i}", uid="aaa"))
            det.add_event(_observation(f"output {i}", uid="bbb"))
        result = det.check()
        assert result.pattern != "repeating_action_observation"


class TestStuckDetectorRepeatingError:
    def test_stuck_repeating_error(self):
        """3 consecutive identical error events → is_stuck=True, pattern=repeating_action_error."""
        det = StuckDetector()
        for _ in range(StuckDetector.REPEAT_ERROR_THRESHOLD):
            det.add_event(_error("Permission denied", uid="err1"))
        result = det.check()
        assert result.is_stuck is True
        assert result.pattern == "repeating_action_error"

    def test_not_stuck_with_two_errors(self):
        """Only 2 errors (< threshold=3) should not trigger."""
        det = StuckDetector()
        for _ in range(StuckDetector.REPEAT_ERROR_THRESHOLD - 1):
            det.add_event(_error("Permission denied", uid="err1"))
        result = det.check()
        assert result.pattern != "repeating_action_error"

    def test_not_stuck_with_different_errors(self):
        """3 different error messages should not trigger."""
        det = StuckDetector()
        for i in range(StuckDetector.REPEAT_ERROR_THRESHOLD):
            det.add_event(_error(f"Error variant {i}", uid="err1"))
        result = det.check()
        assert result.pattern != "repeating_action_error"


class TestStuckDetectorPingPong:
    def test_stuck_pingpong(self):
        """Alternate A/B events 6 times → is_stuck=True, pattern=pingpong."""
        det = StuckDetector()
        event_a = {"type": "action", "action": "read", "args": "file_a.py"}
        event_b = {"type": "action", "action": "read", "args": "file_b.py"}
        for _ in range(StuckDetector.PINGPONG_THRESHOLD // 2):
            det.add_event(event_a)
            det.add_event(event_b)
        result = det.check()
        assert result.is_stuck is True
        assert result.pattern == "pingpong"

    def test_not_stuck_insufficient_pingpong(self):
        """Only 4 alternating events (< threshold=6) should not trigger pingpong."""
        det = StuckDetector()
        event_a = {"type": "action", "action": "read", "args": "file_a.py"}
        event_b = {"type": "action", "action": "read", "args": "file_b.py"}
        for _ in range(2):  # 4 events total
            det.add_event(event_a)
            det.add_event(event_b)
        result = det.check()
        assert result.pattern != "pingpong"


class TestStuckDetectorMonologue:
    def test_stuck_monologue(self):
        """3 consecutive message events with no tool_use → is_stuck=True, pattern=monologue."""
        det = StuckDetector()
        for _ in range(StuckDetector.MONOLOGUE_THRESHOLD):
            det.add_event(_message("I think I should...", uid="msg1"))
        result = det.check()
        assert result.is_stuck is True
        assert result.pattern == "monologue"

    def test_not_stuck_message_with_tool(self):
        """Message event containing tool_use should NOT count toward monologue."""
        det = StuckDetector()
        for _ in range(StuckDetector.MONOLOGUE_THRESHOLD):
            det.add_event({
                "type": "message",
                "text": "Using a tool",
                "tool_use": {"name": "bash"},
                "id": "m1",
            })
        result = det.check()
        assert result.pattern != "monologue"

    def test_not_stuck_two_messages(self):
        """Only 2 consecutive plain messages (< threshold=3) should not trigger."""
        det = StuckDetector()
        for _ in range(StuckDetector.MONOLOGUE_THRESHOLD - 1):
            det.add_event(_message("Still thinking", uid="m1"))
        result = det.check()
        assert result.pattern != "monologue"


class TestStuckDetectorNormal:
    def test_not_stuck_normal(self):
        """Varied, realistic events should not trigger stuck detection."""
        det = StuckDetector()
        events = [
            {"type": "action", "action": "bash", "args": "ls", "id": "1"},
            {"type": "observation", "content": "file1.py  file2.py", "id": "2"},
            {"type": "action", "action": "bash", "args": "cat file1.py", "id": "3"},
            {"type": "observation", "content": "def hello(): pass", "id": "4"},
            {"type": "message", "text": "I see the code.", "id": "5"},
            {"type": "action", "action": "bash", "args": "python file1.py", "id": "6"},
            {"type": "observation", "content": "Hello!", "id": "7"},
        ]
        for e in events:
            det.add_event(e)
        result = det.check()
        assert result.is_stuck is False
        assert result.pattern is None
        assert result.nudge is None


class TestEventKeyStripsUuids:
    def test_event_key_strips_uuids(self):
        """Two events identical except for UUID values should produce the same key."""
        det = StuckDetector()
        e1 = {
            "type": "action",
            "action": "bash",
            "args": "ls /tmp",
            "id": "550e8400-e29b-41d4-a716-446655440000",
        }
        e2 = {
            "type": "action",
            "action": "bash",
            "args": "ls /tmp",
            "id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        }
        assert det._event_key(e1) == det._event_key(e2)

    def test_event_key_differs_on_content(self):
        """Events with different structural content should produce different keys."""
        det = StuckDetector()
        e1 = {"type": "action", "action": "bash", "args": "ls /tmp"}
        e2 = {"type": "action", "action": "bash", "args": "ls /var"}
        assert det._event_key(e1) != det._event_key(e2)

    def test_event_key_strips_timestamps(self):
        """Events differing only in a numeric timestamp value should produce the same key."""
        det = StuckDetector()
        e1 = {"type": "action", "action": "bash", "args": "echo hi", "ts": "1727654400"}
        e2 = {"type": "action", "action": "bash", "args": "echo hi", "ts": "1727654999"}
        # ts is a top-level ephemeral field stripped by _event_key
        # Even if not stripped by name, the value normalisation handles it
        k1 = det._event_key(e1)
        k2 = det._event_key(e2)
        # Both "ts" values are numeric strings; after stripping, they should match
        assert k1 == k2


class TestStuckResult:
    def test_result_fields_when_not_stuck(self):
        det = StuckDetector()
        det.add_event({"type": "action", "action": "ls"})
        result = det.check()
        assert isinstance(result, StuckResult)
        assert result.is_stuck is False
        assert result.pattern is None
        assert result.iteration == 1

    def test_iteration_increments(self):
        det = StuckDetector()
        for i in range(5):
            det.add_event({"type": "action", "action": f"cmd{i}"})
        result = det.check()
        assert result.iteration == 5


# ---------------------------------------------------------------------------
# ContextBuilder tests
# ---------------------------------------------------------------------------


class TestContextBuilderFormat:
    def test_context_builder_format(self):
        """Output must contain '## Brain Context' header."""
        cb = ContextBuilder()
        out = cb.build(
            activated_nodes={"memory": "some content"},
            lessons=["Always write tests first."],
            reflections=["Last run succeeded."],
        )
        assert "## Brain Context" in out

    def test_context_builder_contains_sections(self):
        """Output should contain all three section headers when data is provided."""
        cb = ContextBuilder()
        out = cb.build(
            activated_nodes={"code_skill": "def foo(): ..."},
            lessons=["Use type hints."],
            reflections=["Refactored utils.py successfully."],
        )
        assert "### Active Associations" in out
        assert "### Relevant Lessons" in out
        assert "### Recent Reflections" in out

    def test_empty_inputs(self):
        """Empty inputs still return the header at minimum."""
        cb = ContextBuilder()
        out = cb.build({}, [], [])
        assert "## Brain Context" in out

    def test_node_content_snippet(self):
        """Node content truncated to 100 chars appears in output."""
        cb = ContextBuilder()
        content = "x" * 200
        out = cb.build({"big_node": content}, [], [])
        assert "x" * 100 in out
        assert "x" * 101 not in out


class TestContextBuilderTruncates:
    def test_context_builder_truncates(self):
        """Large node list must be truncated to max_chars."""
        cb = ContextBuilder()
        large_nodes = {f"node_{i}": "content " * 50 for i in range(100)}
        out = cb.build(large_nodes, [], [], max_chars=500)
        assert len(out) <= 500 + 3  # allow for trailing '...'

    def test_context_builder_truncates_at_boundary(self):
        """Output never exceeds max_chars (ignoring possible '...' suffix)."""
        cb = ContextBuilder()
        nodes = {f"node_{i}": f"{'A' * 200}" for i in range(50)}
        lessons = [f"Lesson {i} — " + "detail " * 20 for i in range(50)]
        reflections = [f"Reflection {i} — " + "note " * 20 for i in range(50)]
        for max_chars in [200, 500, 1000, 2000]:
            out = cb.build(nodes, lessons, reflections, max_chars=max_chars)
            assert len(out) <= max_chars + 3, (
                f"Output length {len(out)} exceeds max_chars={max_chars} + 3"
            )

    def test_context_builder_small_max(self):
        """Very small max_chars should still not crash."""
        cb = ContextBuilder()
        out = cb.build({"k": "v"}, ["lesson"], ["reflection"], max_chars=10)
        assert len(out) <= 13  # 10 + "..."
