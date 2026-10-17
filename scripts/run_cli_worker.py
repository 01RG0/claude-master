"""Phase 2 CLI Worker: executes real Claude Code CLI scenarios (S1, S2 strict) in isolated sandboxes."""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.eval_queue import SwarmQueue, log_ledger_event, log_bug

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

EVAL_DIR = ROOT / "data" / "eval"
RESULTS_DIR = EVAL_DIR / "results"


def wilson_ci_95(successes: int, total: int) -> Tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    z = 1.95996
    p = successes / total
    denom = 1.0 + (z * z) / total
    centre = (p + (z * z) / (2.0 * total)) / denom
    spread = (z * math.sqrt((p * (1.0 - p) / total) + (z * z) / (4.0 * total * total))) / denom
    return (round(max(0.0, centre - spread), 4), round(min(1.0, centre + spread), 4))


def choose_free_port(host="127.0.0.1") -> int:
    with socket.socket() as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def wait_health(url: str, timeout: int = 25) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def evaluate_s1_strict_oracle(task_dir: str, stdout: str, rc: int) -> bool:
    """STRICT S1 oracle: files must exist strictly in task_dir and end with '-done'."""
    if rc != 0:
        return False
    try:
        txt_files = [f for f in os.listdir(task_dir) if f.endswith(".txt")]
    except OSError:
        return False
    if len(txt_files) < 3:
        return False
    return all(
        open(os.path.join(task_dir, f), encoding="utf-8").read().strip().endswith("-done")
        for f in txt_files
    )


def evaluate_s2_strict_oracle(task_dir: str, stdout: str, rc: int) -> bool:
    """STRICT S2 oracle: rc == 0 and 'CHECK-OK-123' in stdout."""
    return rc == 0 and ("CHECK-OK-123" in stdout)


class CliWorker:
    def __init__(self, worker_id: str, gateway_port: Optional[int] = None, reps: int = 10, max_routes: int = 5):
        self.worker_id = worker_id
        self.reps = reps
        self.max_routes = max_routes
        self.gateway_port = gateway_port or choose_free_port()
        self.queue = SwarmQueue()
        self.results_dir = RESULTS_DIR / worker_id
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.results_file = self.results_dir / "results.jsonl"
        self.gw_proc: Optional[subprocess.Popen] = None

    def start_gateway(self) -> bool:
        health_url = f"http://127.0.0.1:{self.gateway_port}/health"
        if wait_health(health_url, timeout=1):
            logger.info(f"Gateway already active on port {self.gateway_port}")
            return True

        gw_exe = ROOT / "gateway" / "gateway.exe"
        cfg_file = ROOT / "gateway" / "config.json"
        env_file = ROOT / ".env"

        logger.info(f"Starting isolated gateway for {self.worker_id} on port {self.gateway_port}...")
        self.gw_proc = subprocess.Popen(
            [
                str(gw_exe),
                "-config", str(cfg_file),
                "-env-file", str(env_file),
                "-listen", f"127.0.0.1:{self.gateway_port}",
            ],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        ok = wait_health(health_url, timeout=20)
        if not ok:
            logger.error(f"Failed to start gateway on port {self.gateway_port}")
            if self.gw_proc:
                self.gw_proc.terminate()
        return ok

    def stop_gateway(self):
        if self.gw_proc:
            try:
                self.gw_proc.terminate()
                self.gw_proc.wait(timeout=3)
            except Exception:
                self.gw_proc.kill()
            self.gw_proc = None

    def run_claude(
        self,
        prompt: str,
        taskdir: str,
        profile_dir: str,
        model: str,
        timeout: int = 90,
    ) -> Tuple[int, str, float, Dict[str, Any]]:
        cmd = [
            "claude", "-p", prompt,
            "--allowedTools", "Write", "Edit", "Read", "Bash", "Glob", "Grep", "Task",
            "--permission-mode", "dontAsk",
            "--output-format", "json",
            "--add-dir", taskdir,
            "--model", model,
        ]

        env = dict(
            os.environ,
            ANTHROPIC_BASE_URL=f"http://127.0.0.1:{self.gateway_port}",
            ANTHROPIC_API_KEY="dummy",
            ANTHROPIC_MODEL=model,
            CLAUDE_CONFIG_DIR=profile_dir,
        )
        env.pop("ANTHROPIC_AUTH_TOKEN", None)

        t0 = time.perf_counter()
        try:
            p = subprocess.run(
                cmd,
                cwd=taskdir,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            dt_ms = (time.perf_counter() - t0) * 1000.0
            stdout = p.stdout or ""
            parsed = {}
            try:
                parsed = json.loads(stdout)
            except Exception:
                pass
            return p.returncode, stdout, dt_ms, parsed
        except subprocess.TimeoutExpired:
            return -1, "TIMEOUT", timeout * 1000.0, {}

    def run(self) -> Dict[str, Any]:
        logger.info(f"CLI Worker {self.worker_id} started. Target reps={self.reps}")
        log_ledger_event(self.worker_id, "cli_validation", "started")

        if not self.start_gateway():
            log_ledger_event(self.worker_id, "cli_validation", "failed", notes="Gateway start failed")
            return {"routes_completed": 0, "error": "Gateway start failed"}

        base_tmp = Path(tempfile.mkdtemp(prefix=f"cm_cli_{self.worker_id}_"))
        routes_completed = 0
        routes_failed = 0

        try:
            while routes_completed + routes_failed < self.max_routes:
                job = self.queue.claim_job(self.worker_id, stage=2, lease_duration=600.0)
                if not job:
                    logger.info("No more eligible Stage 2 CLI jobs in queue.")
                    break

                job_id = job["job_id"]
                route_id = job["route"]
                parts = route_id.split(":", 1)
                raw_model_id = parts[1] if len(parts) > 1 else route_id
                provider = job.get("provider", "unknown")

                logger.info(f"=== CLI Evaluating Route: {route_id} ({raw_model_id} via {provider}) ===")
                self.queue.heartbeat(self.worker_id, job_id, lease_duration=600.0)

                s1_successes = 0
                s1_latencies = []
                s1_reps_data = []

                # S1: Multi-file tool creation
                s1_prompt = "Directly in the current working directory, create a.txt with 'alpha', b.txt with 'beta', c.txt with 'gamma'. Then append '-done' to each of those three files."
                for rep in range(1, self.reps + 1):
                    s1_dir = base_tmp / f"s1_{rep}"
                    s1_prof = base_tmp / f"prof_s1_{rep}"
                    s1_dir.mkdir(parents=True, exist_ok=True)
                    s1_prof.mkdir(parents=True, exist_ok=True)
                    (s1_prof / "settings.json").write_text(json.dumps({
                        "env": {
                            "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{self.gateway_port}",
                            "ANTHROPIC_API_KEY": "dummy",
                            "ANTHROPIC_MODEL": raw_model_id,
                            "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
                            "CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT": "1",
                        }
                    }), encoding="utf-8")

                    rc, out, lat_ms, payload = self.run_claude(
                        prompt=s1_prompt,
                        taskdir=str(s1_dir),
                        profile_dir=str(s1_prof),
                        model=raw_model_id,
                        timeout=90,
                    )
                    passed = evaluate_s1_strict_oracle(str(s1_dir), out, rc)
                    if passed:
                        s1_successes += 1
                    s1_latencies.append(lat_ms)
                    s1_reps_data.append({
                        "rep": rep,
                        "passed": passed,
                        "rc": rc,
                        "latency_ms": round(lat_ms, 2),
                        "num_turns": payload.get("num_turns"),
                        "total_cost_usd": payload.get("total_cost_usd"),
                        "session_id": payload.get("session_id"),
                        "cli_output": payload if payload else out,
                    })
                    logger.info(f"  S1 rep{rep}/{self.reps}: {'PASS' if passed else 'FAIL'} ({lat_ms:.0f}ms)")
                    self.queue.heartbeat(self.worker_id, job_id, lease_duration=600.0)

                    # Early stop condition if first 3 all fail
                    if rep == 3 and s1_successes == 0:
                        logger.info("  Early stop on S1: 3 consecutive failures.")
                        break

                s1_total = len(s1_reps_data)
                s1_rate = round(s1_successes / s1_total, 4) if s1_total > 0 else 0.0
                s1_ci = wilson_ci_95(s1_successes, s1_total)

                # S2: Shell execution
                s2_successes = 0
                s2_latencies = []
                s2_reps_data = []
                s2_prompt = "Run: python check.py. Report its exact output."

                for rep in range(1, self.reps + 1):
                    s2_dir = base_tmp / f"s2_{rep}"
                    s2_prof = base_tmp / f"prof_s2_{rep}"
                    s2_dir.mkdir(parents=True, exist_ok=True)
                    s2_prof.mkdir(parents=True, exist_ok=True)
                    (s2_prof / "settings.json").write_text(json.dumps({
                        "env": {
                            "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{self.gateway_port}",
                            "ANTHROPIC_API_KEY": "dummy",
                            "ANTHROPIC_MODEL": raw_model_id,
                            "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
                            "CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT": "1",
                        }
                    }), encoding="utf-8")
                    (s2_dir / "check.py").write_text('print("CHECK-OK-123")\n', encoding="utf-8")

                    rc, out, lat_ms, payload = self.run_claude(
                        prompt=s2_prompt,
                        taskdir=str(s2_dir),
                        profile_dir=str(s2_prof),
                        model=raw_model_id,
                        timeout=60,
                    )
                    passed = evaluate_s2_strict_oracle(str(s2_dir), out, rc)
                    if passed:
                        s2_successes += 1
                    s2_latencies.append(lat_ms)
                    s2_reps_data.append({
                        "rep": rep,
                        "passed": passed,
                        "rc": rc,
                        "latency_ms": round(lat_ms, 2),
                        "num_turns": payload.get("num_turns"),
                        "total_cost_usd": payload.get("total_cost_usd"),
                        "session_id": payload.get("session_id"),
                        "cli_output": payload if payload else out,
                    })
                    logger.info(f"  S2 rep{rep}/{self.reps}: {'PASS' if passed else 'FAIL'} ({lat_ms:.0f}ms)")
                    self.queue.heartbeat(self.worker_id, job_id, lease_duration=600.0)

                    if rep == 3 and s2_successes == 0:
                        logger.info("  Early stop on S2: 3 consecutive failures.")
                        break

                s2_total = len(s2_reps_data)
                s2_rate = round(s2_successes / s2_total, 4) if s2_total > 0 else 0.0
                s2_ci = wilson_ci_95(s2_successes, s2_total)

                # Save raw artifact
                safe_fname = job_id.replace(":", "_").replace("/", "_") + ".json"
                artifact_path = self.results_dir / safe_fname
                artifact_record = {
                    "job_id": job_id,
                    "route_id": route_id,
                    "canonical_id": job.get("canonical_id"),
                    "provider": provider,
                    "provider_model_id": raw_model_id,
                    "stage": 2,
                    "state": "done",
                    "timestamp": time.time(),
                    "s1": {
                        "reps": s1_total,
                        "successes": s1_successes,
                        "pass_rate": s1_rate,
                        "ci_95": s1_ci,
                        "mean_latency_ms": round(sum(s1_latencies) / len(s1_latencies), 2) if s1_latencies else 0.0,
                        "reps_data": s1_reps_data,
                    },
                    "s2": {
                        "reps": s2_total,
                        "successes": s2_successes,
                        "pass_rate": s2_rate,
                        "ci_95": s2_ci,
                        "mean_latency_ms": round(sum(s2_latencies) / len(s2_latencies), 2) if s2_latencies else 0.0,
                        "reps_data": s2_reps_data,
                    },
                }
                artifact_path.write_text(json.dumps(artifact_record, indent=2, ensure_ascii=False), encoding="utf-8")

                with open(self.results_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(artifact_record, ensure_ascii=False) + "\n")

                rel_artifact_path = str(artifact_path.relative_to(ROOT)).replace("\\", "/")
                self.queue.complete_job(
                    job_id=job_id,
                    worker_id=self.worker_id,
                    state="done",
                    result_path=rel_artifact_path,
                )
                routes_completed += 1
                logger.info(f"Finished CLI evaluation for {route_id}: S1={s1_rate} (CI={s1_ci}), S2={s2_rate} (CI={s2_ci})")

        finally:
            self.stop_gateway()
            shutil.rmtree(base_tmp, ignore_errors=True)
            log_ledger_event(self.worker_id, "cli_validation", "finished", routes_completed, routes_failed)

        return {"routes_completed": routes_completed, "routes_failed": routes_failed}


def main():
    parser = argparse.ArgumentParser(description="Run Phase 2 CLI Worker")
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--gateway-port", type=int)
    parser.add_argument("--reps", type=int, default=10)
    parser.add_argument("--max-routes", type=int, default=3)
    args = parser.parse_args()

    worker = CliWorker(
        worker_id=args.worker_id,
        gateway_port=args.gateway_port,
        reps=args.reps,
        max_routes=args.max_routes,
    )
    worker.run()


if __name__ == "__main__":
    main()
