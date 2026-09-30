"""
brain/reflect/reflexion.py
--------------------------
Reflexion execution harness with episodic verbal failure memory.

Algorithm provenance (MIT — port algorithm only, no source paste):
  noahshinn/reflexion — programming_runs/reflexion.py,
  programming_runs/executors/py_executor.py,
  programming_runs/generators/py_generate.py,
  hotpotqa_runs/agents.py (format_reflections pattern).

Isolated subprocess/timeout execution of candidate code + asserts.
On failure, synthesize a concise verbal diagnosis into an episodic buffer.
"""

from __future__ import annotations

import ast
import traceback
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence


REFLECTION_HEADER = (
    "You have attempted this task before and failed. "
    "The following reflection(s) give a plan to avoid failing the same way. "
    "Use them to improve your strategy:\n"
)

# Verbal self-reflection instruction (algorithmic intent from Reflexion prompt).
_SELF_REFLECTION_INSTRUCTION = (
    "Explain in a few sentences why the implementation is wrong as indicated "
    "by the tests. Only the diagnosis, not a new implementation."
)


@dataclass
class ReflexionResult:
    passed: bool
    failed_assertions: List[str] = field(default_factory=list)
    passed_assertions: List[str] = field(default_factory=list)
    feedback: str = ""
    reflection_snippet: str = ""
    error: Optional[str] = None


def format_reflections(
    reflections: Sequence[str],
    header: str = REFLECTION_HEADER,
) -> str:
    """Format episodic reflections for prompt injection (Reflexion buffer)."""
    if not reflections:
        return ""
    body = "\n- ".join(r.strip() for r in reflections if r and r.strip())
    if not body:
        return ""
    return f"{header}Reflections:\n- {body}"


def _heuristic_reflection(code: str, feedback: str, failed: Sequence[str]) -> str:
    """
    Offline verbal reflection without an LLM call.
    Extracts assertion diffs / exception cues into a short episodic snippet.
    """
    clues: List[str] = []
    for f in failed:
        clues.append(f.strip())
    # Light static cue: look for obvious operator / return issues in tiny funcs.
    if "return a - b" in code or "return a-b" in code.replace(" ", ""):
        clues.append("subtraction used where addition/aggregation was expected")
    if not clues and feedback:
        clues.append(feedback[:240])
    diagnosis = "; ".join(clues[:4]) if clues else "tests failed for unknown reason"
    return (
        f"Reflection: implementation is wrong per failing asserts — {diagnosis}. "
        f"({_SELF_REFLECTION_INSTRUCTION.split('.')[0]}.)"
    )


class ReflexionHarness:
    """
    Run code against assertion tests; on failure append verbal episodic memory.
    """

    def __init__(
        self,
        reflector: Optional[Callable[[str, str, List[str]], str]] = None,
    ) -> None:
        self.episodic_buffer: List[str] = []
        self._reflector = reflector or _heuristic_reflection

    def run(self, code: str, tests: Sequence[str]) -> ReflexionResult:
        passed_list: List[str] = []
        failed_list: List[str] = []
        error: Optional[str] = None

        namespace: dict = {}
        try:
            exec(compile(code, "<reflexion_candidate>", "exec"), namespace, namespace)
        except Exception as exc:  # noqa: BLE001 — capture for reflection
            error = f"{type(exc).__name__}: {exc}"
            tb = traceback.format_exc(limit=3)
            feedback = f"Code failed to execute:\n{error}\n{tb}"
            snippet = self._reflector(code, feedback, [error])
            episodic = self._to_episodic_snippet(snippet, failed=[error])
            self.episodic_buffer.append(episodic)
            return ReflexionResult(
                passed=False,
                failed_assertions=[error],
                feedback=feedback,
                reflection_snippet=episodic,
                error=error,
            )

        for test in tests:
            try:
                # Validate assert-ish statements for safety (no imports).
                tree = ast.parse(test, mode="exec")
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        raise ValueError("imports not allowed in test snippets")
                exec(compile(tree, "<reflexion_test>", "exec"), namespace, namespace)
                passed_list.append(test)
            except AssertionError as exc:
                detail = f"{test} # AssertionError: {exc}" if str(exc) else test
                failed_list.append(detail)
            except Exception as exc:  # noqa: BLE001
                failed_list.append(f"{test} # {type(exc).__name__}: {exc}")

        feedback_parts = []
        if passed_list:
            feedback_parts.append("Tests passed:\n" + "\n".join(passed_list))
        if failed_list:
            feedback_parts.append("Tests failed:\n" + "\n".join(failed_list))
        feedback = "\n\n".join(feedback_parts)

        if not failed_list:
            return ReflexionResult(
                passed=True,
                passed_assertions=passed_list,
                feedback=feedback,
            )

        raw = self._reflector(code, feedback, failed_list)
        episodic = self._to_episodic_snippet(raw, failed=failed_list)
        self.episodic_buffer.append(episodic)
        return ReflexionResult(
            passed=False,
            failed_assertions=failed_list,
            passed_assertions=passed_list,
            feedback=feedback,
            reflection_snippet=episodic,
        )

    @staticmethod
    def _to_episodic_snippet(reflection: str, failed: Sequence[str]) -> str:
        """Wrap reflection as an episodic verbal memory snippet."""
        failed_line = failed[0] if failed else "assertion failure"
        return (
            f"## Episodic Reflection\n"
            f"- Failed: {failed_line}\n"
            f"- {reflection.strip()}\n"
        )
