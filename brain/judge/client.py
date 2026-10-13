"""
DrexClient: HTTP client for the Drex System-1 decision gateway (rewrite).

Docs: https://console.nace.ai/docs (Drex quickstart, questions, state,
reading-answers, errors-and-retries, limits, pricing, models).

Endpoint:  POST https://console.nace.ai/v1/systemone  (Bearer NACE_API_KEY)
Models:    GET  https://console.nace.ai/v1/models     (never hardcode)

Request body: {"model": <id>|omitted, "state": str|json, "questions": {...}}
  - noul:   {"type":"noul","instructions":str,"criteria":{"true":...,"false":...}}
  - choice: {"type":"choice","instructions":str,"criteria":{label:str|null}}
  - score:  {"type":"score","instructions":str,"criteria":[levels...]}
  - 1..512 questions per call; state+questions <= 1 MiB.

Response answers:
  - noul:   {"type":"noul","noul":p}                      p = P(yes)
  - choice: {"type":"choice","choice":label,"confidence":c,"probabilities":{...}}
  - score:  {"type":"score","score":E[level],"legend":[...],"probabilities":{"0":..},"confidence":c}
  - usage:  {"input_tokens":N,"output_tokens":M} (billed: input only, success only)
  - evaluation_time_ms: model time (not round trip); request_id in body + headers.

Reliability (per errors-and-retries guide):
  - Retry: 429 rate_limit_error, 529 overloaded, 500 internal_error, network/timeout.
    Honor retry-after-ms / retry-after when present, else capped exp backoff+jitter.
  - Never retry: 401 authentication_error, 402 insufficient_credit/payment_required,
    422 invalid_request_error.
  - Client timeout default 60s (Drex waits up to 55s for the model). Fast-gate
    callers (hook path, <10ms budget) must pass a short timeout explicitly and
    rely on fail-open + cache — see DecisionTaker in decision_taker.py.
  - Circuit breaker: after N consecutive failures the client short-circuits to
    fail-open for a cooldown instead of hammering a dead endpoint.
  - Whole system runs with Drex down (degraded mode): evaluate() returns
    {"_fail_open": True, ...} and callers fall back to deterministic rules.

Cost accounting: price per 1M input tokens by model
  (drex-v1.0 $0.04, drex-v1.5 $0.05, drex-v2.0 $0.06 — refreshed from /v1/models
  when reachable; fallback table otherwise). Only successful responses are billed.

Logging: every decision (state, questions, answers, confidence, latency,
outcome/caller, model, usage, cost) is appended as one JSON line to
<log_dir>/decisions.jsonl and decisions.md (default:
tempdir/claude-master-logs; overridable via CLAUDE_DECISIONS_LOG_DIR). Docs are
never written at runtime — docs/decisions.md is ADR-only. Secrets are never logged (state passed here
must already be redacted by the caller — see GatingPolicy).
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from brain.judge.cache import DrexCache

# ---------------------------------------------------------------------------
# Constants (per docs)
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://console.nace.ai"
SYSTEMONE_PATH = "/v1/systemone"
MODELS_PATH = "/v1/models"

# Fallback price table ($ per 1M input tokens). Refreshed from /v1/models
# description when reachable; docs table as of 2026-10-06.
FALLBACK_PRICES = {
    "drex-v1.0": 0.04,
    "drex-v1.5": 0.05,
    "drex-v2.0": 0.06,
    "drex-latest": 0.06,
}

# HTTP statuses worth retrying (429/500/529 + network errors). Never 401/402/422.
RETRYABLE_STATUS = {408, 429, 500, 529}

# API keys look like nace_sk_<43 url-safe chars>; redact anything resembling one.
_KEY_RE = re.compile(r"nace_sk_[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9_-]{8,}|DREX_API_KEY\s*=\s*\S+")


def redact(text: str) -> str:
    return _KEY_RE.sub("[REDACTED]", text)


# ---------------------------------------------------------------------------
# Repo-root + key loading (robust .env parsing)
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path:
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / ".git").exists() or (current / ".env").exists():
            return current
        current = current.parent
    return Path.cwd()


def _parse_dotenv_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines tolerating `export`, quotes, spaces, comments."""
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        # strip inline comments not inside quotes
        if "#" in v and not (v.startswith('"') or v.startswith("'")):
            v = v.split("#", 1)[0].strip()
        v = v.strip("\"'")
        if k:
            out[k] = v
    return out


def _load_api_key(repo_root: Path) -> Optional[str]:
    # Docs use NACE_API_KEY; legacy code used DREX_API_KEY. Accept both plus
    # the bare `drex_api` alias found in user .env files (case-insensitive).
    aliases = ("NACE_API_KEY", "DREX_API_KEY", "DREX_API", "NACE_API")
    for env_name in aliases:
        key = os.environ.get(env_name) or os.environ.get(env_name.lower())
        if key and key.strip():
            return key.strip().strip("\"'")
    for candidate in (repo_root / ".env", repo_root.parent / ".env", Path.cwd() / ".env"):
        if candidate.exists():
            vals = _parse_dotenv_file(candidate)
            upper = {k.upper(): v for k, v in vals.items()}
            for env_name in aliases:
                if upper.get(env_name):
                    return upper[env_name]
    return None


def _default_log_dir() -> Path:
    from brain.paths import default_log_dir as _d

    return Path(os.environ.get("CLAUDE_DECISIONS_LOG_DIR") or _d())


def _log_decision_jsonl(
    log_dir: Path,
    record: dict[str, Any],
) -> None:
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "decisions.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
    except OSError:
        pass


def _log_decision_markdown(
    log_dir: Path,
    state: str,
    questions: dict,
    response: dict,
    latency_ms: float,
) -> None:
    # Human-readable mirror of decisions.jsonl. Lives in the runtime log dir,
    # NEVER under docs/: doc trees are for versioned ADRs, runtime logs are
    # per-machine outputs (churn there would dirty every git status).
    decisions_file = log_dir / "decisions.md"
    try:
        decisions_file.parent.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime())
        req_id = response.get("request_id", "local_cached")
        model = response.get("model", "unknown")
        lines = [
            f"\n### Decision Record: `{req_id}`",
            f"- **Timestamp**: `{timestamp}`",
            f"- **Model**: `{model}` | **Latency**: `{latency_ms:.1f}ms`",
            f"- **State Evaluation Context**:\n```text\n{redact(state)}\n```",
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
    except OSError:
        pass


# ---------------------------------------------------------------------------
# DrexClient
# ---------------------------------------------------------------------------


class DrexClient:
    """
    HTTP wrapper for Drex POST /v1/systemone with caching, retries,
    circuit breaker, dynamic model resolution and cost accounting.

    Parameters
    ----------
    api_key : explicit key (else NACE_API_KEY/DREX_API_KEY from env/.env).
    base_url : Drex console base (default https://console.nace.ai).
    model : pinned model id, "drex-latest", or None to omit (server default
        drex-v2.0). Resolved via GET /v1/models at startup when reachable.
    timeout_s : per-attempt timeout seconds. Default 60.0 per docs (model can
        take up to 55s). Fast-gate callers pass ~0.15 and rely on fail-open.
    max_retries : retries for 429/500/529/network (default 2, i.e. 3 attempts).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        model: Optional[str] = None,
        timeout_ms: Optional[int] = None,
        timeout_s: float = 60.0,
        max_retries: int = 2,
    ) -> None:
        self._repo_root = _find_repo_root()
        self._api_key: str = api_key or _load_api_key(self._repo_root) or ""
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        if timeout_ms is not None:
            timeout_s = timeout_ms / 1000.0
        self._timeout_s: float = timeout_s
        self._max_retries = max_retries
        self._cache = DrexCache()
        self._model_override = model  # explicit pin or None
        self._resolved_model: Optional[str] = None
        self._models_cache: Optional[list[dict]] = None
        self._models_fetched_at: float = 0.0
        # circuit breaker
        self._consec_failures = 0
        self._breaker_open_until = 0.0
        # accounting (only successful responses are billed)
        self.total_input_tokens = 0
        self.total_calls = 0
        self.total_fail_open = 0
        self.total_cost_usd = 0.0
        self._prices = dict(FALLBACK_PRICES)

    # -- models ----------------------------------------------------------
    def list_models(self, timeout_s: float = 10.0) -> list[dict]:
        """GET /v1/models. Cached 1h. Returns [] when unreachable.

        Real shape (2026-10): {"models": [{"name": "drex-v1.0", ...}]}.
        Also accepts {"data": [...]} and bare [...] for forward-compat.
        Normalises each entry to {"id": <name>, ...} so callers use .get("id").
        """
        if self._models_cache is not None and (time.monotonic() - self._models_fetched_at) < 3600:
            return self._models_cache
        url = f"{self._base_url}{MODELS_PATH}"
        req = urllib.request.Request(url, headers=self._auth_headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return self._models_cache or []
        models: object = None
        if isinstance(data, dict):
            models = data.get("models", data.get("data"))
        elif isinstance(data, list):
            models = data
        if not isinstance(models, list):
            models = []
        norm: list[dict] = []
        for m in models:
            if isinstance(m, dict):
                d = dict(m)
                if "id" not in d and d.get("name"):
                    d["id"] = d["name"]
                norm.append(d)
        models = norm
        self._models_cache = models
        self._models_fetched_at = time.monotonic()
        # refresh prices from description if present ("$0.06 per ...")
        for m in models:
            if isinstance(m, dict) and m.get("id") and m.get("price_per_1m"):
                try:
                    self._prices[m["id"]] = float(m["price_per_1m"])
                except (TypeError, ValueError):
                    pass
        return models

    def resolve_model(self) -> Optional[str]:
        """Return the model id to send (None = omit, server defaults to v2.0)."""
        if self._model_override:
            return self._model_override
        if self._resolved_model:
            return self._resolved_model
        models = self.list_models()
        ids = {m.get("id") for m in models if isinstance(m, dict)}
        for candidate in ("drex-v2.0", "drex-latest", "drex-v1.5", "drex-v1.0"):
            if candidate in ids:
                self._resolved_model = candidate
                return candidate
        # unreachable or unexpected shape: omit model, server picks default
        return None

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    # -- core ------------------------------------------------------------
    def evaluate(self, state: str | Any, questions: dict) -> dict:
        """Evaluate state+questions via Drex with cache + retries + fail-open."""
        cached = self._cache.get(str(state), questions)
        if cached is not None:
            return cached
        if time.monotonic() < self._breaker_open_until:
            self.total_fail_open += 1
            return {"_fail_open": True, "_reason": "circuit_open"}

        model = self.resolve_model()
        body: dict[str, Any] = {"state": state, "questions": questions}
        if model:
            body["model"] = model
        payload = json.dumps(body).encode("utf-8")
        if len(payload) > 1_048_576:
            return {"_fail_open": True, "_reason": "body_over_1MiB"}

        url = f"{self._base_url}{SYSTEMONE_PATH}"
        last_err: Optional[str] = None
        latency_ms = 0.0
        for attempt in range(self._max_retries + 1):
            req = urllib.request.Request(url, data=payload, headers=self._auth_headers(), method="POST")
            start_t = time.perf_counter()
            try:
                with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                    raw = resp.read().decode("utf-8")
                    data = json.loads(raw)
                    request_id = resp.headers.get("x-request-id") or data.get("request_id")
                    if request_id and "request_id" not in data:
                        data["request_id"] = request_id
            except urllib.error.HTTPError as exc:
                latency_ms = (time.perf_counter() - start_t) * 1000.0
                status = exc.code
                try:
                    retry_after_ms = exc.headers.get("retry-after-ms") or exc.headers.get("retry-after")
                except Exception:
                    retry_after_ms = None
                if status in RETRYABLE_STATUS and attempt < self._max_retries:
                    try:
                        wait_s = float(retry_after_ms) / 1000.0 if retry_after_ms else None
                    except (TypeError, ValueError):
                        wait_s = None
                    if wait_s is None:
                        capped = min(0.5 * (2**attempt), 5.0)
                        wait_s = capped / 2 + random.random() * (capped / 2)
                    time.sleep(min(wait_s, 30.0))
                    last_err = f"http_{status}_retrying"
                    continue
                last_err = f"http_{status}"
                self._note_failure()
                self.total_fail_open += 1
                return {"_fail_open": True, "_reason": last_err, "_status": status}
            except Exception as exc:  # timeout / connection / DNS
                latency_ms = (time.perf_counter() - start_t) * 1000.0
                if attempt < self._max_retries and self._timeout_s >= 1.0:
                    capped = min(0.5 * (2**attempt), 5.0)
                    time.sleep(capped / 2 + random.random() * (capped / 2))
                    last_err = f"{type(exc).__name__}_retrying"
                    continue
                self._note_failure()
                self.total_fail_open += 1
                return {"_fail_open": True, "_reason": type(exc).__name__}
            else:
                latency_ms = (time.perf_counter() - start_t) * 1000.0
                self._note_success()
                self._account(data)
                record = {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "request_id": data.get("request_id", ""),
                    "model": data.get("model", model or ""),
                    "state": redact(str(state))[:4000],
                    "questions": questions,
                    "answers": data.get("answers", {}),
                    "latency_ms": round(latency_ms, 1),
                    "usage": data.get("usage", {}),
                }
                _log_decision_jsonl(_default_log_dir(), record)
                _log_decision_markdown(_default_log_dir(), str(state), questions, data, latency_ms)
                self._cache.set(str(state), questions, data)
                return data
        self._note_failure()
        self.total_fail_open += 1
        return {"_fail_open": True, "_reason": last_err or "retries_exhausted"}

    # -- helpers ---------------------------------------------------------
    def _note_success(self) -> None:
        self._consec_failures = 0

    def _note_failure(self) -> None:
        self._consec_failures += 1
        if self._consec_failures >= 5:
            self._breaker_open_until = time.monotonic() + 60.0
            self._consec_failures = 0

    def _account(self, data: dict) -> None:
        try:
            usage = data.get("usage", {}) or {}
            n = int(usage.get("input_tokens", 0) or 0)
            model = data.get("model", "") or ""
            price = self._prices.get(model, 0.06)
            self.total_input_tokens += n
            self.total_calls += 1
            self.total_cost_usd += n / 1_000_000 * price
        except Exception:
            pass

    def cost_summary(self) -> dict[str, Any]:
        return {
            "calls": self.total_calls,
            "input_tokens": self.total_input_tokens,
            "cost_usd": round(self.total_cost_usd, 6),
            "fail_open": self.total_fail_open,
        }

    @property
    def evaluate_cached_pct(self) -> float:
        return self._cache.hit_rate * 100.0
