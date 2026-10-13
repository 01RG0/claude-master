"""brain/judge/decision_taker.py — clean Decision Taker interface (rewrite).

Other components never touch DrexClient directly; they call DecisionTaker,
which owns: question shaping, confidence thresholds, deterministic fallbacks,
and decision logging. Drex down => degraded mode (rule fallback), never crash.

Decisions wired (mission Phase 2):
  gateway: which provider/model should handle this request  -> decide_provider
  guard:   allow / block / ask-user for a tool call         -> decide_guard
  judge:   did this action succeed, was it useful           -> decide_judge
  learning: should this event be stored, how important      -> decide_store
  sleep:   is it time to consolidate, what to merge/forget -> decide_sleep
  watchdog: restart, wait or escalate                       -> decide_watchdog

Confidence rule (docs/reading-answers): Drex returns probabilities, WE choose
thresholds. Above threshold act on Drex; below it fall back to deterministic
rules or escalate. Thresholds below are initial values; calibrate from logged
decisions in <log_dir>/decisions.jsonl (see docs/test-report.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from brain.judge.client import DrexClient

Action = Literal["act", "fallback", "escalate"]


@dataclass
class Decision:
    action: str
    value: Any = None
    confidence: Optional[float] = None
    source: str = "rule"  # drex | rule | cache | fail_open
    reason: str = ""
    raw: dict = field(default_factory=dict)


class DecisionTaker:
    """Facade over DrexClient with per-decision thresholds and rule fallbacks."""

    # Initial thresholds — calibrate from real logged decisions, not guesses.
    GUARD_BLOCK_THRESHOLD = 0.85   # noul P(harm) above this => block
    GUARD_ASK_THRESHOLD = 0.55     # between ask and block => ask-user
    JUDGE_SUCCESS_THRESHOLD = 0.6  # noul P(success) above this => success
    STORE_THRESHOLD = 0.5          # score importance above this => store
    SLEEP_THRESHOLD = 0.6          # noul P(consolidation_due) above this => run
    PROVIDER_CONF_THRESHOLD = 0.55  # choice confidence below this => bandit order

    def __init__(
        self,
        client: Optional[DrexClient] = None,
        fast_timeout_s: float = 1.0,
        bg_timeout_s: float = 60.0,
        budget_usd: float = 5.0,
    ) -> None:
        # Two clients sharing nothing but config: fast-gate (risky-path only)
        # and background (sleep/judge/batch). Measured 2026-10-13, drex-v2.0,
        # 220 live calls: roundtrip p50=538ms p95=616ms p99=783ms; a 150ms
        # budget would fail open ~100% — 1.0s covers p99 with margin. The hot
        # hook path never calls Drex for safe/not-risky commands (rule-only).
        self.fast = client or DrexClient(timeout_s=fast_timeout_s, max_retries=0)
        self._bg_timeout = bg_timeout_s
        self._bg: Optional[DrexClient] = None
        self.budget_usd = budget_usd

    @property
    def bg(self) -> DrexClient:
        if self._bg is None:
            self._bg = DrexClient(timeout_s=self._bg_timeout, max_retries=2)
        return self._bg

    def _over_budget(self, c: DrexClient) -> bool:
        return c.total_cost_usd >= self.budget_usd

    # -- guard ---------------------------------------------------------
    GUARD_QUESTION = {
        "risk": {
            "type": "noul",
            "instructions": (
                "Is this tool action likely to cause irreversible harm, data loss, "
                "or security exposure in a developer workspace?"
            ),
        }
    }

    def decide_guard(self, tool_name: str, category: str) -> Decision:
        """Allow/block/ask for a tool call. State is redacted (no raw commands)."""
        state = f"Tool: {tool_name}, Category: {category}"
        if self._over_budget(self.fast):
            return Decision("act", "allow", None, "rule", "drex budget exhausted; fail-open allow")
        resp = self.fast.evaluate(state, self.GUARD_QUESTION)
        if resp.get("_fail_open"):
            return Decision("act", "allow", None, "fail_open", "drex unreachable; fail-open allow", resp)
        p = (resp.get("answers", {}).get("risk", {}) or {}).get("noul")
        if p is None:
            return Decision("act", "allow", None, "rule", "malformed drex answer; allow")
        if p > self.GUARD_BLOCK_THRESHOLD:
            return Decision("act", "block", p, "drex", f"P(harm)={p:.3f} > {self.GUARD_BLOCK_THRESHOLD}", resp)
        if p > self.GUARD_ASK_THRESHOLD:
            return Decision("escalate", "ask-user", p, "drex", f"P(harm)={p:.3f} in ask band", resp)
        return Decision("act", "allow", p, "drex", f"P(harm)={p:.3f} below ask band", resp)

    # -- judge ---------------------------------------------------------
    JUDGE_QUESTIONS = {
        "succeeded": {"type": "noul", "instructions": "Did this action succeed?"},
        "usefulness": {
            "type": "score",
            "instructions": "How useful was this action for the task?",
            "criteria": ["useless", "slightly useful", "useful", "critical"],
        },
    }

    def decide_judge(self, summary: str) -> Decision:
        resp = self.bg.evaluate(summary, self.JUDGE_QUESTIONS)
        if resp.get("_fail_open"):
            return Decision("fallback", None, None, "fail_open", "drex down; caller uses heuristics", resp)
        ans = resp.get("answers", {})
        p = (ans.get("succeeded", {}) or {}).get("noul")
        score = (ans.get("usefulness", {}) or {}).get("score")
        conf = (ans.get("succeeded", {}) or {}).get("confidence")
        ok = p is not None and p > self.JUDGE_SUCCESS_THRESHOLD
        return Decision("act", {"success": ok, "p": p, "usefulness": score}, conf, "drex", "", resp)

    # -- learning / store ----------------------------------------------
    STORE_QUESTIONS = {
        "importance": {
            "type": "score",
            "instructions": "How important is this event to remember for future tasks?",
            "criteria": ["noise", "minor", "important", "critical"],
        }
    }

    def decide_store(self, summary: str) -> Decision:
        resp = self.fast.evaluate(summary, self.STORE_QUESTIONS)
        if resp.get("_fail_open"):
            return Decision("fallback", {"store": True, "importance": 1.0}, None, "fail_open",
                            "drex down; store by default", resp)
        score = ((resp.get("answers", {}) or {}).get("importance", {}) or {}).get("score", 0)
        conf = ((resp.get("answers", {}) or {}).get("importance", {}) or {}).get("confidence")
        if conf is not None and conf < 0.5:
            return Decision("fallback", {"store": score is not None and score >= 1.0, "importance": score},
                            conf, "drex", "low confidence; rule fallback", resp)
        store = score is not None and score >= 1.0
        return Decision("act", {"store": store, "importance": score}, conf, "drex", "", resp)

    # -- sleep ----------------------------------------------------------
    SLEEP_QUESTIONS = {
        "due": {"type": "noul", "instructions": "Is it time to consolidate memory (sleep)?"},
        "strategy": {
            "type": "choice",
            "instructions": "What should sleep focus on?",
            "criteria": {
                "merge": "Merge duplicate or overlapping memories",
                "forget": "Forget low-value or stale memories",
                "distill": "Distill lessons and skills from episodes",
            },
        },
    }

    def decide_sleep(self, stats_summary: str) -> Decision:
        resp = self.bg.evaluate(stats_summary, self.SLEEP_QUESTIONS)
        if resp.get("_fail_open"):
            # deterministic fallback: nightly schedule handled by watchdog
            return Decision("fallback", {"run": False, "strategy": "distill"}, None, "fail_open",
                            "drex down; watchdog schedule applies", resp)
        ans = resp.get("answers", {})
        p = (ans.get("due", {}) or {}).get("noul", 0)
        strat = (ans.get("strategy", {}) or {}).get("choice", "distill")
        conf = (ans.get("strategy", {}) or {}).get("confidence")
        return Decision("act", {"run": p > self.SLEEP_THRESHOLD, "strategy": strat}, conf, "drex", "", resp)

    # -- gateway provider choice ----------------------------------------
    def decide_provider(self, request_summary: str, candidates: list[str]) -> Decision:
        if not candidates:
            return Decision("fallback", None, None, "rule", "no candidates")
        if len(candidates) == 1:
            return Decision("act", candidates[0], 1.0, "rule", "single candidate")
        criteria = {c: None for c in candidates[:8]}  # cap labels for token cost
        resp = self.fast.evaluate(
            request_summary,
            {"route": {"type": "choice", "instructions": "Which provider/model should handle this request?",
                       "criteria": criteria}},
        )
        if resp.get("_fail_open"):
            return Decision("fallback", candidates[0], None, "fail_open", "drex down; bandit order", resp)
        ans = (resp.get("answers", {}) or {}).get("route", {}) or {}
        pick, conf = ans.get("choice"), ans.get("confidence")
        if pick not in criteria or (conf is not None and conf < self.PROVIDER_CONF_THRESHOLD):
            return Decision("fallback", candidates[0], conf, "drex", "low confidence; bandit order", resp)
        return Decision("act", pick, conf, "drex", "", resp)

    # -- watchdog --------------------------------------------------------
    WATCHDOG_QUESTIONS = {
        "action": {
            "type": "choice",
            "instructions": "A supervised process failed its health check. What should the watchdog do?",
            "criteria": {
                "restart": "Restart the process now",
                "wait": "Wait and re-check on the next interval",
                "escalate": "Stop restarting and escalate to the operator",
            },
        }
    }

    def decide_watchdog(self, failure_summary: str, restarts: int) -> Decision:
        if restarts >= 5:  # deterministic guardrail: never restart-loop forever
            return Decision("act", "escalate", 1.0, "rule", "restart budget exhausted")
        resp = self.fast.evaluate(failure_summary, self.WATCHDOG_QUESTIONS)
        if resp.get("_fail_open"):
            return Decision("act", "restart" if restarts < 3 else "wait", None, "fail_open",
                            "drex down; default policy", resp)
        ans = (resp.get("answers", {}) or {}).get("action", {}) or {}
        pick, conf = ans.get("choice", "restart"), ans.get("confidence")
        if conf is not None and conf < 0.5:
            return Decision("fallback", "restart", conf, "drex", "low confidence; default restart", resp)
        return Decision("act", pick, conf, "drex", "", resp)
