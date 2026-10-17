"""brain/api/services/models_service.py — Model catalog aggregation, pinning, banning, probing, and comparison.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
import sqlite3

from brain.api.database import get_setting, set_setting, log_audit_event
from brain.api.models import ModelInfo
from brain.api.services.config_service import (
    get_repo_root,
    read_gateway_config,
    get_capabilities_path,
)
from brain.routing.privacy_policy import has_valid_zero_retention_evidence


_LITELLM_PRICES_CACHE: Optional[Dict[str, Any]] = None


def load_litellm_prices() -> Dict[str, Any]:
    global _LITELLM_PRICES_CACHE
    if _LITELLM_PRICES_CACHE is not None:
        return _LITELLM_PRICES_CACHE
    p = get_repo_root() / "data" / "litellm-prices.json"
    if p.exists():
        try:
            _LITELLM_PRICES_CACHE = json.loads(p.read_text(encoding="utf-8"))
            return _LITELLM_PRICES_CACHE
        except Exception:
            pass
    _LITELLM_PRICES_CACHE = {}
    return _LITELLM_PRICES_CACHE


_CATALOG_ROUTES_CACHE: Optional[Dict[str, Any]] = None


def load_catalog_routes() -> Dict[str, Any]:
    global _CATALOG_ROUTES_CACHE
    if _CATALOG_ROUTES_CACHE is not None:
        return _CATALOG_ROUTES_CACHE
    p = get_repo_root() / "data" / "catalog" / "routes.json"
    if p.exists():
        try:
            _CATALOG_ROUTES_CACHE = json.loads(p.read_text(encoding="utf-8"))
            return _CATALOG_ROUTES_CACHE
        except Exception:
            pass
    _CATALOG_ROUTES_CACHE = {}
    return _CATALOG_ROUTES_CACHE


def get_model_pricing(model_id: str) -> Dict[str, float]:
    prices = load_litellm_prices()
    # Direct lookup or clean prefix lookup
    info = prices.get(model_id)
    if not info:
        for k, v in prices.items():
            if k.endswith(f"/{model_id}") or k == model_id:
                info = v
                break
    if info:
        in_cost = float(info.get("input_cost_per_token", 0.0) or 0.0)
        out_cost = float(info.get("output_cost_per_token", 0.0) or 0.0)
        return {
            "input_per_million": round(in_cost * 1_000_000, 4),
            "output_per_million": round(out_cost * 1_000_000, 4),
        }

    # Catalog routes fallback
    routes = load_catalog_routes()
    for r in routes.values():
        if r.get("provider_model_id") == model_id or r.get("canonical_id") == model_id or model_id in r.get("route_id", ""):
            pr = r.get("pricing", {})
            if pr and (pr.get("prompt_per_m", 0.0) > 0 or pr.get("completion_per_m", 0.0) > 0):
                return {
                    "input_per_million": round(float(pr.get("prompt_per_m", 0.0)), 4),
                    "output_per_million": round(float(pr.get("completion_per_m", 0.0)), 4),
                }

    return {"input_per_million": 0.0, "output_per_million": 0.0}


def get_model_context(model_id: str) -> int:
    prices = load_litellm_prices()
    info = prices.get(model_id) or {}
    tokens = info.get("max_input_tokens") or info.get("max_tokens")
    if isinstance(tokens, int):
        return tokens
    return 128000


def get_all_models(conn: Optional[sqlite3.Connection] = None) -> List[ModelInfo]:
    config = read_gateway_config()
    cap_path = get_capabilities_path()
    caps_data: Dict[str, Any] = {}
    if cap_path.exists():
        try:
            caps_data = json.loads(cap_path.read_text(encoding="utf-8")).get("providers", {})
        except Exception:
            pass

    # Read model_stats from DB
    stats_map: Dict[str, Dict[str, Any]] = {}
    if conn:
        try:
            rows = conn.execute("SELECT * FROM model_stats").fetchall()
            for r in rows:
                stats_map[r["model_id"]] = dict(r)
        except Exception:
            pass

    # Pinned/banned state
    pinned_banned = get_setting(conn, "pinned_banned_models", default={"pinned": [], "banned": []}) if conn else {"pinned": [], "banned": []}
    overrides = get_setting(conn, "model_capability_overrides", default={}) if conn else {}

    models_dict: Dict[str, ModelInfo] = {}

    # 1. Models from config.json
    for p in config.get("providers", []):
        prov_name = p.get("name", "unknown")
        p_privacy = p.get("privacy_policy", "zero_retention")
        p_compliant = has_valid_zero_retention_evidence(prov_name) if p_privacy == "zero_retention" else False
        for m in p.get("models", []):
            st = stats_map.get(m, {})
            succ = st.get("successes", 0)
            fail = st.get("failures", 0)
            total_calls = succ + fail
            lat = round(st.get("total_latency_ms", 0.0) / total_calls, 1) if total_calls > 0 else 0.0

            # Determine tool calling support: gemma models on OpenRouter do not support function calling, and embedding/reranking models do not support tools
            has_tools = "gemma" not in m.lower() and "embed" not in m.lower() and "rerank" not in m.lower()
            caps = {
                "vision": "vision" in m.lower() or "gemini" in m.lower(),
                "tools": has_tools,
                "streaming": True,
                "reasoning": "r1" in m.lower() or "reasoning" in m.lower() or "thinking" in m.lower(),
            }
            if m in overrides:
                caps.update(overrides[m])

            models_dict[m] = ModelInfo(
                model_id=m,
                provider=prov_name,
                capabilities=caps,
                context_window=get_model_context(m),
                pricing=get_model_pricing(m),
                successes=succ,
                failures=fail,
                latency_p50_ms=lat,
                is_pinned=m in pinned_banned.get("pinned", []),
                is_banned=m in pinned_banned.get("banned", []),
                privacy_policy=p_privacy,
                zero_retention_compliant=p_compliant,
            )

    # 2. Add models from capabilities.json
    for prov_name, prov_info in caps_data.items():
        p_privacy = "zero_retention"
        p_compliant = has_valid_zero_retention_evidence(prov_name)
        for m in prov_info.get("models", []):
            if m == "*" or m in models_dict:
                continue
            has_tools = "gemma" not in m.lower() and "embed" not in m.lower() and "rerank" not in m.lower()
            caps = {
                "vision": "vision" in m.lower() or "omni" in m.lower(),
                "tools": has_tools,
                "streaming": True,
                "reasoning": "think" in m.lower() or "r1" in m.lower(),
            }
            if m in overrides:
                caps.update(overrides[m])

            models_dict[m] = ModelInfo(
                model_id=m,
                provider=prov_name,
                capabilities=caps,
                context_window=get_model_context(m),
                pricing=get_model_pricing(m),
                successes=0,
                failures=0,
                latency_p50_ms=0.0,
                is_pinned=m in pinned_banned.get("pinned", []),
                is_banned=m in pinned_banned.get("banned", []),
                privacy_policy=p_privacy,
                zero_retention_compliant=p_compliant,
            )

    return list(models_dict.values())


async def pin_models(models: List[str], conn: Optional[sqlite3.Connection] = None, gateway_url: str = "http://127.0.0.1:8080") -> bool:
    if conn:
        state = get_setting(conn, "pinned_banned_models", default={"pinned": [], "banned": []})
        pinned_set = set(state.get("pinned", []))
        pinned_set.update(models)
        banned_set = set(state.get("banned", [])) - set(models)
        set_setting(conn, "pinned_banned_models", {"pinned": list(pinned_set), "banned": list(banned_set)})
        log_audit_event(conn, action="pin_models", details={"models": models})

    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            await client.post(f"{gateway_url}/v1/admin/keys", json={"action": "pin", "provider": "admin", "models": models})
    except Exception:
        pass
    return True


async def ban_models(models: List[str], conn: Optional[sqlite3.Connection] = None, gateway_url: str = "http://127.0.0.1:8080") -> bool:
    if conn:
        state = get_setting(conn, "pinned_banned_models", default={"pinned": [], "banned": []})
        banned_set = set(state.get("banned", []))
        banned_set.update(models)
        pinned_set = set(state.get("pinned", [])) - set(models)
        set_setting(conn, "pinned_banned_models", {"pinned": list(pinned_set), "banned": list(banned_set)})
        log_audit_event(conn, action="ban_models", details={"models": models})

    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            await client.post(f"{gateway_url}/v1/admin/keys", json={"action": "ban", "provider": "admin", "models": models})
    except Exception:
        pass
    return True


def save_capability_override(model_id: str, capabilities: Dict[str, bool], conn: sqlite3.Connection) -> None:
    overrides = get_setting(conn, "model_capability_overrides", default={})
    overrides[model_id] = capabilities
    set_setting(conn, "model_capability_overrides", overrides)
    log_audit_event(conn, action="override_capabilities", details={"model_id": model_id, "capabilities": capabilities})


def compare_models(model_ids: List[str], conn: Optional[sqlite3.Connection] = None) -> List[ModelInfo]:
    all_models = get_all_models(conn)
    model_map = {m.model_id: m for m in all_models}
    return [model_map[mid] for mid in model_ids if mid in model_map]
