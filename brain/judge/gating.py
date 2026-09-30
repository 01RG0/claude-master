"""
GatingPolicy: Pre-execution safety gate using regex heuristics + Drex AI.

Architecture:
1. SAFE_PATTERNS  -> immediately allow without Drex call.
2. Not matching RISKY_PATTERNS -> allow (not risky).
3. RISKY_PATTERNS match -> call Drex with *redacted* descriptor.
   - noul > 0.85 -> block
   - fail_open   -> allow (errata item 3)
   - otherwise   -> allow

Privacy contract: raw command strings are NEVER sent to Drex.
Only 'Tool: {tool_name}, Category: {category}' is transmitted.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from brain.judge.client import DrexClient

# ---------------------------------------------------------------------------
# Pattern registries
# ---------------------------------------------------------------------------

RISKY_PATTERNS: list[str] = [
    r"rm\s+-rf",
    r"curl.*(\||>|>>)\s*sh",
    r"sudo\s+",
    r"chmod\s+777",
    r"eval\(",
    r"exec\(",
    r"import\s+os.*system",
    r"ANTHROPIC_API_KEY",
    r"\.env",
]

SAFE_PATTERNS: list[str] = [
    r"^git\s+(status|log|diff|add|commit)",
    r"^python3?\s+-m\s+pytest",
    r"^go\s+test",
    r"^npm\s+test",
    r"^make\s+",
]

# Pre-compiled for performance
_COMPILED_RISKY = [re.compile(p, re.IGNORECASE) for p in RISKY_PATTERNS]
_COMPILED_SAFE = [re.compile(p, re.IGNORECASE) for p in SAFE_PATTERNS]

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class GatingResult:
    """Outcome of a single gate() evaluation."""
    allow: bool
    source: str                       # safe_pattern|not_risky|drex_approved|drex_blocked|fail_open
    probability: Optional[float] = field(default=None)
    reason: str = field(default="")

# ---------------------------------------------------------------------------
# GatingPolicy
# ---------------------------------------------------------------------------

class GatingPolicy:
    """
    Evaluates whether a proposed command/tool invocation should be permitted.

    Parameters
    ----------
    client : DrexClient
        Configured Drex client instance used for AI-based risk adjudication.
    """

    # Expose pattern lists as class attributes for test introspection
    RISKY_PATTERNS = RISKY_PATTERNS
    SAFE_PATTERNS = SAFE_PATTERNS

    # Drex question definitions
    _DREX_QUESTIONS = {
        "risk_check": {
            "type": "noul",
            "instructions": (
                "Is this tool category likely to cause irreversible harm, "
                "data loss, or security exposure in a developer workspace?"
            ),
        }
    }

    def __init__(self, client: DrexClient) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Heuristic helpers
    # ------------------------------------------------------------------

    @staticmethod
    def is_risky(command: str) -> bool:
        """Return True if command matches any RISKY_PATTERN."""
        return any(p.search(command) for p in _COMPILED_RISKY)

    @staticmethod
    def is_safe(command: str) -> bool:
        """Return True if command matches any SAFE_PATTERN."""
        return any(p.search(command) for p in _COMPILED_SAFE)

    # ------------------------------------------------------------------
    # Main gate
    # ------------------------------------------------------------------

    def gate(self, command_summary: str, tool_name: str) -> GatingResult:
        """
        Decide whether to allow execution.

        The raw `command_summary` is used ONLY for local regex evaluation.
        Drex receives only 'Tool: {tool_name}, Category: {category}'.

        Parameters
        ----------
        command_summary : str
            Human-readable description / command string (NOT transmitted to Drex).
        tool_name : str
            Name of the tool being invoked (used in Drex state descriptor).

        Returns
        -------
        GatingResult
        """
        # Fast path 1: explicitly safe
        if self.is_safe(command_summary):
            return GatingResult(
                allow=True,
                source="safe_pattern",
                reason=f"Command matched a safe pattern.",
            )

        # Fast path 2: not risky
        if not self.is_risky(command_summary):
            return GatingResult(
                allow=True,
                source="not_risky",
                reason="No risky pattern detected.",
            )

        # Slow path: call Drex with redacted descriptor
        # Determine category from risky pattern names for the descriptor
        category = self._classify_category(command_summary)
        drex_state = f"Tool: {tool_name}, Category: {category}"

        response = self._client.evaluate(drex_state, self._DREX_QUESTIONS)

        # Fail-open
        if response.get("_fail_open"):
            return GatingResult(
                allow=True,
                source="fail_open",
                reason="Drex unreachable; fail-open policy applied.",
            )

        noul: Optional[float] = response.get("answers", {}).get("risk_check", {}).get("noul")

        if noul is not None and noul > 0.85:
            return GatingResult(
                allow=False,
                source="drex_blocked",
                probability=noul,
                reason=f"Drex risk probability {noul:.4f} exceeds threshold 0.85.",
            )

        return GatingResult(
            allow=True,
            source="drex_approved",
            probability=noul,
            reason=f"Drex risk probability {noul} is within acceptable range.",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_category(command: str) -> str:
        """Map a command to a coarse risk category string for Drex."""
        lower = command.lower()
        if "rm" in lower:
            return "file_deletion"
        if "curl" in lower or "wget" in lower:
            return "network_pipe"
        if "sudo" in lower:
            return "privilege_escalation"
        if "chmod" in lower:
            return "permission_change"
        if "eval" in lower or "exec" in lower:
            return "dynamic_code_execution"
        if "import os" in lower:
            return "shell_injection"
        if "api_key" in lower or ".env" in lower:
            return "secret_exposure"
        return "unknown_risky"
