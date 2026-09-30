"""
DrexClient: HTTP client for the Drex System-1 decision gateway.

- Loads DREX_API_KEY from env or repo-root .env file.
- Implements fail-open semantics (timeout > 150 ms or any exception -> _fail_open).
- Logs every decision to docs/decisions.md (append).
- Caches successful results via DrexCache.
"""

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from brain.judge.cache import DrexCache

# ---------------------------------------------------------------------------
# Repo-root resolution (mirrors scripts/drex_client.py logic)
# ---------------------------------------------------------------------------

def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (.git or .env present)."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / ".git").exists() or (current / ".env").exists():
            return current
        current = current.parent
    return Path.cwd()


def _load_api_key(repo_root: Path) -> Optional[str]:
    """Load DREX_API_KEY from environment or repo-root .env file."""
    key = os.environ.get("DREX_API_KEY")
    if key:
        return key.strip("\"'")

    env_file = repo_root / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("DREX_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("\"'")

    # Parent-directory fallback (matches scripts/drex_client.py)
    parent_env = repo_root.parent / ".env"
    if parent_env.exists():
        with open(parent_env, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("DREX_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("\"'")

    return None


def _log_decision(
    repo_root: Path,
    state: str,
    questions: dict,
    response: dict,
    latency_ms: float,
) -> None:
    """Append a structured decision record to docs/decisions.md."""
    decisions_file = repo_root / "docs" / "decisions.md"
    decisions_file.parent.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime())
    req_id = response.get("request_id", "local_cached")
    model = response.get("model", "drex-v1.5")

    lines = [
        f"\n### Decision Record: `{req_id}`",
        f"- **Timestamp**: `{timestamp}`",
        f"- **Model**: `{model}` | **Latency**: `{latency_ms:.1f}ms`",
        f"- **State Evaluation Context**:\n```text\n{state}\n```",
        "- **Questions & Calibrated Answers**:",
    ]

    for q_id, q_body in questions.items():
        ans = response.get("answers", {}).get(q_id, {})
        lines.append(f"  - **`{q_id}`** ({q_body.get('type', 'unknown')}):")
        lines.append(f"    - Instructions: *{q_body.get('instructions', '')}*")
        if "choice" in ans:
            lines.append(
                f"    - **Selected Choice**: `{ans.get('choice')}` "
                f"(Confidence: `{ans.get('confidence', 0):.4f}`)"
            )
            lines.append(f"    - Probabilities: `{json.dumps(ans.get('probabilities', {}))}`")
        elif "noul" in ans:
            lines.append(f"    - **Probability (True)**: `{ans.get('noul', 0):.4f}`")
        elif "score" in ans:
            lines.append(f"    - **Score**: `{ans.get('score', 0):.4f}`")

    lines.append("---\n")

    with open(decisions_file, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


# ---------------------------------------------------------------------------
# DrexClient
# ---------------------------------------------------------------------------

class DrexClient:
    """
    HTTP wrapper for Drex /v1/systemone with caching and fail-open semantics.

    Parameters
    ----------
    api_key : str | None
        Explicit API key. If None, auto-loads from env / .env file.
    base_url : str
        Drex API base URL.
    model : str
        Drex model identifier.
    timeout_ms : int
        Hard timeout in milliseconds. Requests exceeding this are treated as
        fail-open (returns {'_fail_open': True}).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://drex.nace.ai",
        model: str = "drex-v1.5",
        timeout_ms: int = 150,
    ) -> None:
        self._repo_root = _find_repo_root()
        self._api_key: str = api_key or _load_api_key(self._repo_root) or ""
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_s: float = timeout_ms / 1000.0
        self._cache = DrexCache()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, state: str, questions: dict) -> dict:
        """
        Evaluate state+questions via Drex, with caching and fail-open.

        Returns
        -------
        dict
            Drex response on success, or {'_fail_open': True} on timeout/error.
        """
        # 1. Cache check
        cached = self._cache.get(state, questions)
        if cached is not None:
            return cached

        # 2. HTTP call
        url = f"{self._base_url}/v1/systemone"
        payload = json.dumps(
            {"model": self._model, "state": state, "questions": questions}
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        start_t = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            # Fail-open: any network error, timeout, or HTTP error
            return {"_fail_open": True}

        latency_ms = (time.perf_counter() - start_t) * 1000.0

        # 3. Log and cache
        _log_decision(self._repo_root, state, questions, data, latency_ms)
        self._cache.set(state, questions, data)
        return data

    @property
    def evaluate_cached_pct(self) -> float:
        """Cache hit rate as a percentage (0–100)."""
        return self._cache.hit_rate * 100.0
