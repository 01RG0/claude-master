"""
DrexCache: Simple dict-based TTL cache for Drex evaluation results.

Keyed on (state_hash, question_hash) derived from SHA-256 of sorted JSON.
Expired entries are auto-purged on access.
"""

import hashlib
import json
import time
from typing import Optional


class DrexCache:
    """In-memory TTL cache for Drex /v1/systemone responses."""

    def __init__(self) -> None:
        # Maps str key -> (result: dict, expires_at: float)
        self._store: dict[str, tuple[dict, float]] = {}
        self._hits: int = 0
        self._misses: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, state: str, questions: dict) -> Optional[dict]:
        """Return cached result if present and not expired, else None."""
        key = self._key(state, questions)
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None
        result, expires_at = entry
        if time.monotonic() >= expires_at:
            # Auto-purge expired entry
            del self._store[key]
            self._misses += 1
            return None
        self._hits += 1
        return result

    def set(self, state: str, questions: dict, result: dict, ttl_s: float = 300.0) -> None:
        """Store result with given TTL in seconds."""
        key = self._key(state, questions)
        expires_at = time.monotonic() + ttl_s
        self._store[key] = (result, expires_at)

    @property
    def hit_count(self) -> int:
        return self._hits

    @property
    def miss_count(self) -> int:
        return self._misses

    @property
    def total(self) -> int:
        return self._hits + self._misses

    @property
    def hit_rate(self) -> float:
        """Cache hit rate as a fraction in [0, 1]."""
        t = self.total
        return self._hits / t if t > 0 else 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _key(state: str, questions: dict) -> str:
        """Deterministic SHA-256 key derived from state + sorted questions JSON."""
        payload = json.dumps({"state": state, "questions": questions}, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
