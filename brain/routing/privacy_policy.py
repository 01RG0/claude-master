"""brain/routing/privacy_policy.py — Provenance and retention verification for routing.

Directive 6: When privacy_policy == 'zero_retention' or require_zero_retention == true,
router MUST exclude any route/model lacking recorded zero-retention evidence with valid provenance.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


_POLICIES_CACHE: Optional[Dict[str, Dict[str, Any]]] = None
_CUSTOM_OVERRIDES: Dict[str, Dict[str, Any]] = {}


def get_repo_root() -> Path:
    # Walk up to find data/ or pyproject.toml
    cur = Path(__file__).resolve().parent
    for _ in range(5):
        if (cur / "data" / "privacy" / "provider_policies.json").exists() or (cur / "pyproject.toml").exists():
            return cur
        cur = cur.parent
    return Path(os.getcwd())


def get_provider_policies_path() -> Path:
    override = os.environ.get("CLAUDE_MASTER_PRIVACY_POLICIES")
    if override:
        return Path(override)
    p = get_repo_root() / "data" / "privacy" / "provider_policies.json"
    if p.exists():
        return p
    # Fallback to relative path
    alt = Path("data/privacy/provider_policies.json").resolve()
    return alt


def load_provider_policies(force_reload: bool = False) -> Dict[str, Dict[str, Any]]:
    global _POLICIES_CACHE
    if _POLICIES_CACHE is not None and not force_reload:
        res = dict(_POLICIES_CACHE)
        res.update(_CUSTOM_OVERRIDES)
        return res

    path = get_provider_policies_path()
    policies: Dict[str, Dict[str, Any]] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for k, v in data.get("providers", {}).items():
                policies[k.lower().strip()] = v
        except Exception:
            pass

    _POLICIES_CACHE = policies
    res = dict(_POLICIES_CACHE)
    res.update(_CUSTOM_OVERRIDES)
    return res


def get_provider_policy(provider: str) -> Optional[Dict[str, Any]]:
    policies = load_provider_policies()
    return policies.get(provider.lower().strip())


def has_valid_zero_retention_evidence(provider: str) -> bool:
    """Verifies that the provider has recorded zero-retention evidence with valid provenance.

    Checks:
      1. Provider is recorded in provider_policies.json
      2. zero_retention_compliant is True
      3. Account is explicitly covered (account_covered is True)
      4. Provenance identifier is present, non-empty, and verified (not unverified)
      5. Source URL is present and non-empty
      6. Verification date is present and non-empty
    """
    if not provider:
        return False
    rec = get_provider_policy(provider)
    if not rec:
        return False
    if not rec.get("zero_retention_compliant", False):
        return False
    if rec.get("account_covered") is False:
        return False
    prov = str(rec.get("provenance", "")).strip()
    if not prov or prov.startswith("unverified") or prov.startswith("public"):
        return False
    url = str(rec.get("source_url", "")).strip()
    if not url:
        return False
    vdate = str(rec.get("verified_date", "")).strip()
    if not vdate:
        return False
    return True


def register_provider_policy(provider: str, policy: Dict[str, Any]) -> None:
    """Registers or overrides a provider policy in memory (used by tests and dynamic plugins)."""
    key = provider.lower().strip()
    _CUSTOM_OVERRIDES[key] = policy
    if _POLICIES_CACHE is not None:
        _POLICIES_CACHE[key] = policy


def clear_policy_overrides() -> None:
    """Clears custom runtime policy overrides."""
    global _CUSTOM_OVERRIDES, _POLICIES_CACHE
    _CUSTOM_OVERRIDES.clear()
    _POLICIES_CACHE = None


def list_provider_policies() -> Dict[str, Dict[str, Any]]:
    """Returns all recorded provider policies."""
    return load_provider_policies()
