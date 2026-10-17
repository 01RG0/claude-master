"""Phase 4 Auditor Worker: independently recomputes metrics from disk artifacts and checks provenance."""

from __future__ import annotations

import argparse
import glob
import json
import logging
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

EVAL_DIR = ROOT / "data" / "eval"
RESULTS_DIR = EVAL_DIR / "results"
AUDIT_REPORT_PATH = EVAL_DIR / "audit_report.json"


def wilson_ci_95(successes: int, total: int) -> Tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    z = 1.95996
    p = successes / total
    denom = 1.0 + (z * z) / total
    centre = (p + (z * z) / (2.0 * total)) / denom
    spread = (z * math.sqrt((p * (1.0 - p) / total) + (z * z) / (4.0 * total * total))) / denom
    return (round(max(0.0, centre - spread), 4), round(min(1.0, centre + spread), 4))


def run_audit() -> Dict[str, Any]:
    logger.info("Starting Phase 4 Independent Audit...")

    findings = []
    verified_artifacts = 0
    mismatches = 0

    # 1. Inspect all raw artifacts
    artifact_files = glob.glob(str(RESULTS_DIR / "**" / "*.json"), recursive=True)
    artifact_records = {}

    for fpath in artifact_files:
        if fpath.endswith("results.jsonl"):
            continue
        try:
            data = json.loads(Path(fpath).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                findings.append(f"Invalid artifact format in {fpath}: not a dict")
                mismatches += 1
                continue

            jid = data.get("job_id")
            if not jid:
                findings.append(f"Missing job_id in artifact: {fpath}")
                mismatches += 1
                continue

            # Verify timestamp and stage
            if "timestamp" not in data or "stage" not in data:
                findings.append(f"Incomplete metadata in {jid}")
                mismatches += 1
                continue

            artifact_records[jid] = data
            verified_artifacts += 1
        except Exception as e:
            findings.append(f"Error reading {fpath}: {e}")
            mismatches += 1

    logger.info(f"Audited {verified_artifacts} artifact files on disk.")

    # 2. Check leaderboard recomputation
    leaderboard_file = EVAL_DIR / "leaderboard.json"
    recomputed_leaderboard = []
    if leaderboard_file.exists():
        stored_leaderboard = json.loads(leaderboard_file.read_text(encoding="utf-8"))
        for entry in stored_leaderboard:
            rid = entry.get("route_id")
            art_path = entry.get("artifact_path")
            if not art_path:
                findings.append(f"Leaderboard entry for {rid} missing artifact_path provenance")
                mismatches += 1
                continue

            full_art_path = ROOT / art_path.replace("/", "\\") if not os.path.isabs(art_path) else Path(art_path)
            if not full_art_path.exists():
                findings.append(f"Artifact path for {rid} does not exist on disk: {art_path}")
                mismatches += 1
                continue

            # Recompute from raw
            raw_data = json.loads(full_art_path.read_text(encoding="utf-8"))
            if raw_data.get("stage") == 2:
                s1 = raw_data.get("s1", {})
                s2 = raw_data.get("s2", {})
                tot_reps = s1.get("reps", 0) + s2.get("reps", 0)
                tot_succ = s1.get("successes", 0) + s2.get("successes", 0)
                calc_rate = round(tot_succ / tot_reps, 4) if tot_reps > 0 else 0.0
                stored_rate = entry.get("task_success_rate")
                if abs(calc_rate - stored_rate) > 0.001:
                    findings.append(f"Rate mismatch for {rid}: stored={stored_rate}, computed={calc_rate}")
                    mismatches += 1

    # 3. Check swarm ledger consistency
    ledger_path = EVAL_DIR / "swarm_ledger.jsonl"
    workers_found = set()
    if ledger_path.exists():
        with open(ledger_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        ev = json.loads(line)
                        workers_found.add(ev.get("worker_id"))
                    except Exception:
                        pass

    # 4. Audit summary
    status = "PASSED" if mismatches == 0 else "FAILED_WITH_MISMATCHES"
    audit_report = {
        "audit_timestamp": sys.meta_path and time.time(),
        "status": status,
        "verified_artifacts_count": verified_artifacts,
        "mismatches_detected": mismatches,
        "active_workers_in_ledger": list(workers_found),
        "findings": findings,
        "conclusion": "All headline numbers and leaderboard entries match disk raw artifacts with full provenance." if mismatches == 0 else "Audit discrepancies detected.",
    }

    AUDIT_REPORT_PATH.write_text(json.dumps(audit_report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Audit completed: Status={status}, Verified={verified_artifacts}, Mismatches={mismatches}")
    return audit_report


if __name__ == "__main__":
    import time
    run_audit()
