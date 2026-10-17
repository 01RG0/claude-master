"""Build inventory, classify routes/models through funnel, and initialize queue.jsonl."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from dotenv import dotenv_values

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
EVAL_DIR = ROOT / "data" / "eval"
MODELS_PATH = ROOT / "data" / "catalog" / "models.json"
ROUTES_PATH = ROOT / "data" / "catalog" / "routes.json"
PRIVACY_PATH = ROOT / "data" / "privacy" / "provider_policies.json"
QUEUE_PATH = EVAL_DIR / "queue.jsonl"


def get_broad_family(canonical_id: str, family: str, display_name: str) -> str:
    full = f"{canonical_id} {family} {display_name}".lower()
    if "gpt-oss" in full:
        return "gpt-oss"
    elif "deepseek" in full:
        return "DeepSeek"
    elif "glm" in full or "chatglm" in full:
        return "GLM"
    elif "kimi" in full or "moonshot" in full:
        return "Kimi"
    elif "minimax" in full or "abab" in full:
        return "MiniMax"
    elif "qwen" in full or "qwq" in full or "qvq" in full:
        return "Qwen"
    elif "llama" in full:
        return "Llama"
    elif "gemma" in full:
        return "Gemma"
    elif any(k in full for k in ["mistral", "ministral", "codestral", "mixtral", "pixtral", "devstral"]):
        return "Mistral"
    elif "cohere" in full or "command" in full:
        return "Cohere"
    elif "claude" in full or "anthropic" in full:
        return "Claude"
    elif "grok" in full or "xai" in full:
        return "Grok"
    elif "gemini" in full:
        return "Gemini"
    elif "doubao" in full:
        return "Doubao"
    elif "hunyuan" in full:
        return "Hunyuan"
    elif "ernie" in full or "qianfan" in full:
        return "Ernie"
    elif "gpt" in full or "o1" in full or "o3" in full or "o4" in full or "openai" in full:
        return "GPT"
    return "Other"


def main():
    logger.info("Starting Phase 0: Catalog & Route Inventory Builder...")
    EVAL_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load data
    models: Dict[str, Any] = json.loads(MODELS_PATH.read_text(encoding="utf-8"))
    routes: Dict[str, Any] = json.loads(ROUTES_PATH.read_text(encoding="utf-8"))
    policies: Dict[str, Any] = json.loads(PRIVACY_PATH.read_text(encoding="utf-8")).get("providers", {})
    env = dotenv_values(ROOT / ".env")

    # Map provider to env vars
    provider_key_map = {
        "groq": ["GROQ_API_KEY"],
        "cerebras": ["CEREBRAS_API_KEY"],
        "mistral": ["MISTRAL_API_KEY"],
        "cohere": ["COHERE_API_KEY"],
        "openrouter": ["OPENROUTER_API_KEY"],
        "gemini": ["GEMINI_API_KEY"],
        "pollinations": ["POLLINATIONS_API_KEY"],
        "xai": ["XAI_API_KEY", "ZAI_API_KEY"],
        "alibaba": ["ALIBABA_API_KEY"],
        "aihubmix": ["AIHUBMIX_API_KEY", "APMIX_API_KEY"],
        "apertis": ["APERTIS_API_KEY"],
        "anyapi": ["ANYAPI_API_KEY"],
        "pooled": ["POOLED_API_KEY"],
        "zenmux": ["ZENMUX_API_KEY"],
        "dahl": ["DAHL_API_KEY", "DAHL_API_KEY_2"],
        "tokenharbor": ["TOKEN_HARBOR_API_KEY", "TOKEN_HARBOUR_API_KEY"],
        "codecraft": ["CODECRAFT_API_KEY", "CODECRAFT_BASE_URL"],
        "atessa": ["ATESSA_API_KEY"],
        "aihorde": ["AI_HORDE_ANON_KEY", "AIHORDE_API_KEY"],
    }

    # Provider key presence
    provider_has_key: Dict[str, bool] = {}
    for p, keys in provider_key_map.items():
        provider_has_key[p] = any(k in env and len(env[k].strip()) > 0 for k in keys)

    # 2. Funnel classifications
    # Reason codes:
    # not_chat_capable
    # no_tool_calling
    # alias_unknown_identity
    # no_key_no_access
    # privacy_filter
    # queued (eligible for screening / execution)

    route_funnel_state: Dict[str, Dict[str, Any]] = {}
    model_funnel_state: Dict[str, Dict[str, Any]] = {}

    funnel_counts = {
        "total_canonical_models": len(models),
        "total_routes": len(routes),
        "excluded_not_chat_capable": 0,
        "excluded_no_tool_calling": 0,
        "excluded_alias_unknown_identity": 0,
        "excluded_no_key_no_access": 0,
        "privacy_filter_flagged": 0,
        "eligible_routes": 0,
    }

    # First classify models by capability
    non_chat_types = {"embeddings", "audio_tts", "audio_stt", "image_generation", "rerank"}
    for mid, m in models.items():
        m_type = m.get("type", "unknown")
        is_agentic = m.get("is_agentic", True)
        cid = m.get("canonical_id", mid)

        state = "queued"
        reason = None
        evidence = None

        if m_type in non_chat_types:
            state = "excluded"
            reason = "not_chat_capable"
            evidence = f"Model modality type is '{m_type}'"
        elif not is_agentic or m_type == "classification_guard":
            state = "excluded"
            reason = "no_tool_calling"
            evidence = m.get("non_agentic_reason") or "Model lacks function/tool calling capability"

        model_funnel_state[mid] = {
            "canonical_id": cid,
            "display_name": m.get("display_name"),
            "vendor": m.get("vendor"),
            "family": m.get("family"),
            "broad_family": get_broad_family(cid, m.get("family", ""), m.get("display_name", "")),
            "type": m_type,
            "is_agentic": is_agentic,
            "state": state,
            "reason_code": reason,
            "evidence": evidence,
            "routes": m.get("routes", []),
        }

    # Now classify each route
    alias_patterns = ["auto", "default", "*", "pooled/*", "router", "best", "fastest"]

    for rid, r in routes.items():
        cid = r.get("canonical_id")
        provider = r.get("provider", "unknown")
        raw_model = r.get("provider_model_id", "")
        pricing = r.get("pricing", {})

        m_info = model_funnel_state.get(cid)
        is_aggregator = policies.get(provider, {}).get("aggregator", provider in ["openrouter", "aihubmix", "zenmux", "anyapi"])

        # Check privacy policy
        policy = policies.get(provider, {})
        is_zdr = policy.get("zero_retention_compliant", False)
        privacy_evidence = None
        if not is_zdr:
            privacy_evidence = policy.get("exact_terms") or policy.get("training_policy") or f"Provider '{provider}' lacks verified Zero Data Retention architecture."

        # Evaluate funnel stages in strict order
        state = "queued"
        reason = None
        detail = None

        if m_info and m_info["reason_code"] == "not_chat_capable":
            state = "excluded"
            reason = "not_chat_capable"
            detail = m_info["evidence"]
            funnel_counts["excluded_not_chat_capable"] += 1
        elif m_info and m_info["reason_code"] == "no_tool_calling":
            state = "excluded"
            reason = "no_tool_calling"
            detail = m_info["evidence"]
            funnel_counts["excluded_no_tool_calling"] += 1
        elif any(alias == raw_model.lower() or raw_model.endswith("/*") or "/auto" in raw_model.lower() for alias in ["auto", "default", "*"]):
            state = "excluded"
            reason = "alias_unknown_identity"
            detail = f"Route targets dynamic alias/wildcard '{raw_model}' without deterministic model identity"
            funnel_counts["excluded_alias_unknown_identity"] += 1
        elif not provider_has_key.get(provider, False):
            state = "excluded"
            reason = "no_key_no_access"
            detail = f"No API credentials found in .env for provider '{provider}'"
            funnel_counts["excluded_no_key_no_access"] += 1
        else:
            # Route has key and agentic identity
            if not is_zdr:
                funnel_counts["privacy_filter_flagged"] += 1
            funnel_counts["eligible_routes"] += 1

        route_funnel_state[rid] = {
            "route_id": rid,
            "canonical_id": cid,
            "provider": provider,
            "provider_model_id": raw_model,
            "is_aggregator": is_aggregator,
            "has_key": provider_has_key.get(provider, False),
            "zero_retention_compliant": is_zdr,
            "privacy_evidence": privacy_evidence,
            "pricing": pricing,
            "state": state,
            "reason_code": reason,
            "detail": detail,
            "broad_family": m_info["broad_family"] if m_info else "Unknown",
        }

    # 3. Create job queue entries (Stage 1 screening and Stage 2 validation)
    # queue.jsonl: one job per (route x stage).
    # Fields: job_id, route, stage, state, lease_owner, lease_expiry, attempts, result_path, reason_code
    jobs: List[Dict[str, Any]] = []

    for rid, rinfo in route_funnel_state.items():
        cid = rinfo["canonical_id"]
        provider = rinfo["provider"]
        initial_state = rinfo["state"]  # "queued" or "excluded"
        reason = rinfo["reason_code"]

        # Stage 1 job: Screening
        job_s1 = {
            "job_id": f"s1_{rid}",
            "route": rid,
            "canonical_id": cid,
            "provider": provider,
            "stage": 1,
            "state": initial_state,
            "lease_owner": None,
            "lease_expiry": None,
            "attempts": 0,
            "result_path": None,
            "reason_code": reason,
            "is_aggregator": rinfo["is_aggregator"],
            "zero_retention_compliant": rinfo["zero_retention_compliant"],
            "privacy_evidence": rinfo["privacy_evidence"],
            "pricing": rinfo["pricing"],
            "broad_family": rinfo["broad_family"],
        }
        jobs.append(job_s1)

        # Stage 2 job: CLI validation (initially queued if eligible, or excluded)
        job_s2 = {
            "job_id": f"s2_{rid}",
            "route": rid,
            "canonical_id": cid,
            "provider": provider,
            "stage": 2,
            "state": "queued" if initial_state == "queued" else "excluded",
            "lease_owner": None,
            "lease_expiry": None,
            "attempts": 0,
            "result_path": None,
            "reason_code": reason,
            "is_aggregator": rinfo["is_aggregator"],
            "zero_retention_compliant": rinfo["zero_retention_compliant"],
            "privacy_evidence": rinfo["privacy_evidence"],
            "pricing": rinfo["pricing"],
            "broad_family": rinfo["broad_family"],
        }
        jobs.append(job_s2)

    # Atomic write to queue.jsonl
    from scripts.eval_queue import SwarmQueue
    queue = SwarmQueue(QUEUE_PATH)
    queue.initialize_queue(jobs, overwrite=True)

    # 4. Save inventory artifacts
    (EVAL_DIR / "funnel_counts.json").write_text(json.dumps(funnel_counts, indent=2), encoding="utf-8")
    (EVAL_DIR / "route_funnel.json").write_text(json.dumps(route_funnel_state, indent=2), encoding="utf-8")
    (EVAL_DIR / "model_funnel.json").write_text(json.dumps(model_funnel_state, indent=2), encoding="utf-8")

    # Generate Family breakdown
    family_summary: Dict[str, Any] = {}
    for rid, r in route_funnel_state.items():
        fam = r["broad_family"]
        if fam not in family_summary:
            family_summary[fam] = {
                "family": fam,
                "total_routes": 0,
                "routes_with_key": 0,
                "zdr_compliant_routes": 0,
                "providers": set(),
                "routes": [],
            }
        family_summary[fam]["total_routes"] += 1
        if r["has_key"]:
            family_summary[fam]["routes_with_key"] += 1
        if r["zero_retention_compliant"]:
            family_summary[fam]["zdr_compliant_routes"] += 1
        family_summary[fam]["providers"].add(r["provider"])
        family_summary[fam]["routes"].append({
            "route_id": rid,
            "canonical_id": r["canonical_id"],
            "provider": r["provider"],
            "provider_model_id": r["provider_model_id"],
            "is_aggregator": r["is_aggregator"],
            "has_key": r["has_key"],
            "zero_retention": r["zero_retention_compliant"],
            "state": r["state"],
            "reason_code": r["reason_code"],
        })

    # Convert sets for JSON
    for fam, d in family_summary.items():
        d["providers"] = sorted(list(d["providers"]))

    (EVAL_DIR / "families_inventory.json").write_text(json.dumps(family_summary, indent=2), encoding="utf-8")

    logger.info("Inventory successfully built:")
    logger.info(f"  Canonical models: {funnel_counts['total_canonical_models']}")
    logger.info(f"  Total routes:     {funnel_counts['total_routes']}")
    logger.info(f"  Total jobs in queue: {len(jobs)} ({len(jobs)//2} per stage)")
    logger.info(f"  Eligible routes:  {funnel_counts['eligible_routes']}")
    logger.info(f"  Saved to {QUEUE_PATH}")


if __name__ == "__main__":
    main()
