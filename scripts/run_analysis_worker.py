"""Phase 3 Analysis Worker: generates family tables, privacy exclusion analysis, identity dedup, leaderboard with Wilson CIs, and router exploration update."""

from __future__ import annotations

import argparse
import glob
import json
import logging
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

EVAL_DIR = ROOT / "data" / "eval"
RESULTS_DIR = EVAL_DIR / "results"
QUEUE_PATH = EVAL_DIR / "queue.jsonl"


def wilson_ci_95(successes: int, total: int) -> Tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    z = 1.95996
    p = successes / total
    denom = 1.0 + (z * z) / total
    centre = (p + (z * z) / (2.0 * total)) / denom
    spread = (z * math.sqrt((p * (1.0 - p) / total) + (z * z) / (4.0 * total * total))) / denom
    return (round(max(0.0, centre - spread), 4), round(min(1.0, centre + spread), 4))


def run_analysis() -> Dict[str, Any]:
    logger.info("Starting Phase 3 Analysis...")

    # 1. Load queue, models, routes, policies
    models_path = ROOT / "data" / "catalog" / "models.json"
    routes_path = ROOT / "data" / "catalog" / "routes.json"
    privacy_path = ROOT / "data" / "privacy" / "provider_policies.json"

    models: Dict[str, Any] = json.loads(models_path.read_text(encoding="utf-8"))
    routes: Dict[str, Any] = json.loads(routes_path.read_text(encoding="utf-8"))
    policies: Dict[str, Any] = json.loads(privacy_path.read_text(encoding="utf-8")).get("providers", {})

    queue_jobs = []
    if QUEUE_PATH.exists():
        with open(QUEUE_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        queue_jobs.append(json.loads(line))
                    except Exception:
                        pass

    # 2. Gather all raw artifacts from results directory
    raw_artifacts = []
    for f in glob.glob(str(RESULTS_DIR / "**" / "*.json"), recursive=True):
        if f.endswith("results.jsonl"):
            continue
        try:
            art = json.loads(Path(f).read_text(encoding="utf-8"))
            if isinstance(art, dict) and "job_id" in art:
                art["_file_path"] = f.replace("\\", "/")
                raw_artifacts.append(art)
        except Exception:
            pass

    logger.info(f"Loaded {len(raw_artifacts)} raw artifact files from {RESULTS_DIR}")

    # Index artifacts by job_id and stage
    stage1_results = {}
    stage2_results = {}
    for art in raw_artifacts:
        stage = art.get("stage")
        jid = art.get("job_id")
        if stage == 1:
            stage1_results[jid] = art
        elif stage == 2:
            stage2_results[jid] = art

    # 3. Build Full Leaderboard
    leaderboard = []
    # Combine stage 1 and stage 2 empirical data
    # Priority for leaderboard: routes with stage 2 CLI data or stage 1 screening data
    for art in raw_artifacts:
        rid = art.get("route_id")
        cid = art.get("canonical_id")
        prov = art.get("provider")
        raw_m = art.get("provider_model_id")

        if art.get("stage") == 2:
            s1_info = art.get("s1", {})
            s2_info = art.get("s2", {})
            reps_total = s1_info.get("reps", 0) + s2_info.get("reps", 0)
            succ_total = s1_info.get("successes", 0) + s2_info.get("successes", 0)
            pass_rate = round(succ_total / reps_total, 4) if reps_total > 0 else 0.0
            ci = wilson_ci_95(succ_total, reps_total)

            latencies = [r.get("latency_ms", 0) for r in s1_info.get("reps_data", []) + s2_info.get("reps_data", []) if r.get("latency_ms")]
            mean_lat = round(sum(latencies) / len(latencies), 1) if latencies else 0.0

            pricing_spec = routes.get(rid, {}).get("pricing", {})
            zdr = policies.get(prov, {}).get("zero_retention_compliant", False)

            leaderboard.append({
                "rank": 0,
                "route_id": rid,
                "canonical_id": cid,
                "provider": prov,
                "model": raw_m,
                "eval_stage": "stage2_real_cli",
                "task_success_rate": pass_rate,
                "wilson_ci_95": list(ci),
                "total_n": reps_total,
                "s1_pass_rate": s1_info.get("pass_rate"),
                "s1_n": s1_info.get("reps"),
                "s2_pass_rate": s2_info.get("pass_rate"),
                "s2_n": s2_info.get("reps"),
                "mean_latency_ms": mean_lat,
                "pricing": pricing_spec,
                "zero_retention_compliant": zdr,
                "artifact_path": art.get("_file_path"),
            })
        elif art.get("stage") == 1 and not any(l["route_id"] == rid for l in leaderboard):
            probes = art.get("probes", {})
            inst_p = probes.get("instruction_following", {})
            single_p = probes.get("single_tool_call", {})
            par_p = probes.get("parallel_tool_call", {})

            checks = [inst_p.get("passed", False), single_p.get("passed", False), par_p.get("passed", False)]
            succ = sum(1 for c in checks if c)
            rate = round(succ / 3.0, 4)
            ci = wilson_ci_95(succ, 3)

            ttft = single_p.get("latency_ms", 0)
            zdr = policies.get(prov, {}).get("zero_retention_compliant", False)

            leaderboard.append({
                "rank": 0,
                "route_id": rid,
                "canonical_id": cid,
                "provider": prov,
                "model": raw_m,
                "eval_stage": "stage1_screening",
                "task_success_rate": rate,
                "wilson_ci_95": list(ci),
                "total_n": 3,
                "s1_pass_rate": None,
                "s1_n": 0,
                "s2_pass_rate": None,
                "s2_n": 0,
                "mean_latency_ms": ttft,
                "pricing": routes.get(rid, {}).get("pricing", {}),
                "zero_retention_compliant": zdr,
                "artifact_path": art.get("_file_path"),
            })

    # Sort leaderboard by success rate descending, then latency ascending
    leaderboard.sort(key=lambda x: (-x["task_success_rate"], x["mean_latency_ms"]))
    for i, item in enumerate(leaderboard, 1):
        item["rank"] = i

    # 4. Privacy Exclusions Analysis (quality scored vs policy status)
    privacy_exclusions = []
    for item in leaderboard:
        if not item["zero_retention_compliant"]:
            policy = policies.get(item["provider"], {})
            privacy_exclusions.append({
                "route_id": item["route_id"],
                "canonical_id": item["canonical_id"],
                "provider": item["provider"],
                "measured_task_success_rate": item["task_success_rate"],
                "wilson_ci_95": item["wilson_ci_95"],
                "total_n": item["total_n"],
                "policy_tier": policy.get("policy_tier", "unverified"),
                "reason": policy.get("exact_terms") or policy.get("training_policy") or "No contractual Zero Data Retention guarantee",
                "ui_display_status": "excluded_by_policy",
                "override_available": True,
            })

    # 5. Identity Deduplication across Aggregators
    # Group models across aggregators vs direct providers
    canonical_routes = {}
    for rid, r in routes.items():
        cid = r.get("canonical_id")
        if cid not in canonical_routes:
            canonical_routes[cid] = []
        canonical_routes[cid].append(r)

    dedup_table = []
    for cid, r_list in canonical_routes.items():
        if len(r_list) > 1:
            m_info = models.get(cid, {})
            dedup_table.append({
                "canonical_id": cid,
                "display_name": m_info.get("display_name"),
                "vendor": m_info.get("vendor"),
                "total_routes": len(r_list),
                "routes": [
                    {
                        "route_id": r.get("route_id"),
                        "provider": r.get("provider"),
                        "provider_model_id": r.get("provider_model_id"),
                        "pricing": r.get("pricing"),
                        "is_alias": r.get("provider_model_id") in ["auto", "default", "*"],
                    }
                    for r in r_list
                ],
            })

    # 6. Unmeasured Models & Exploration Plan
    measured_canonicals = set(l["canonical_id"] for l in leaderboard)
    unmeasured_models = []
    for mid, m in models.items():
        cid = m.get("canonical_id", mid)
        if cid not in measured_canonicals:
            unmeasured_models.append({
                "canonical_id": cid,
                "display_name": m.get("display_name"),
                "vendor": m.get("vendor"),
                "family": m.get("family"),
                "type": m.get("type"),
                "is_agentic": m.get("is_agentic"),
                "routes_count": len(m.get("routes", [])),
                "exploration_priority": "high" if m.get("is_agentic") and len(m.get("routes", [])) > 0 else "low",
            })

    # Exploration budget plan
    exploration_plan = {
        "total_unmeasured_models": len(unmeasured_models),
        "agentic_unmeasured": sum(1 for m in unmeasured_models if m["is_agentic"]),
        "capped_exploration_budget_usd": 5.00,
        "max_exploration_calls_per_model": 3,
        "batch_cadence": "hourly_dynamic_bandit",
        "entry_rule": "Unmeasured agentic models enter router candidate pool with initial optimistic prior (alpha=2, beta=1) under a 5% traffic exploration ceiling.",
    }

    # 7. Feed results into Router Data
    router_benchmarks_path = ROOT / "data" / "evals" / "leaderboard.json"
    router_benchmarks = {
        "version": "2.0.0",
        "timestamp": time.time(),
        "total_routes_measured": len(leaderboard),
        "leaderboard": leaderboard,
        "privacy_exclusions": privacy_exclusions,
        "exploration_plan": exploration_plan,
    }
    router_benchmarks_path.write_text(json.dumps(router_benchmarks, indent=2, ensure_ascii=False), encoding="utf-8")

    # Save all analysis artifacts
    (EVAL_DIR / "leaderboard.json").write_text(json.dumps(leaderboard, indent=2, ensure_ascii=False), encoding="utf-8")
    (EVAL_DIR / "privacy_exclusions.json").write_text(json.dumps(privacy_exclusions, indent=2, ensure_ascii=False), encoding="utf-8")
    (EVAL_DIR / "identity_dedup.json").write_text(json.dumps(dedup_table[:50], indent=2, ensure_ascii=False), encoding="utf-8")
    (EVAL_DIR / "unmeasured_exploration.json").write_text(json.dumps({"unmeasured_models": unmeasured_models[:100], "plan": exploration_plan}, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info(f"Analysis complete: Leaderboard has {len(leaderboard)} entries. Router data updated at {router_benchmarks_path}.")
    return {
        "leaderboard_count": len(leaderboard),
        "privacy_exclusions_count": len(privacy_exclusions),
        "dedup_count": len(dedup_table),
        "unmeasured_count": len(unmeasured_models),
    }


if __name__ == "__main__":
    run_analysis()
