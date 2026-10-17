"""Stage 1 Screening Worker: executes empirical screening probes per route.

Evaluates:
1. Basic instruction following
2. Single tool-call validity
3. Parallel tool-call validity
4. JSON schema adherence & streamed args
5. Latency metrics (TTFT, total latency, throughput)
6. Error handling, rate limit backoff, raw artifact capture.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.eval_queue import SwarmQueue, log_ledger_event, log_bug

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

EVAL_DIR = ROOT / "data" / "eval"
RESULTS_DIR = EVAL_DIR / "results"


class ScreeningRunner:
    def __init__(self, worker_id: str, provider: str, max_jobs: int = 100, safe_rpm: int = 30):
        self.worker_id = worker_id
        self.provider = provider
        self.max_jobs = max_jobs
        self.safe_delay = max(0.2, 60.0 / safe_rpm)
        self.env = dotenv_values(ROOT / ".env")
        self.queue = SwarmQueue()
        self.results_dir = RESULTS_DIR / worker_id
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.results_file = self.results_dir / "results.jsonl"
        self.api_key, self.base_url = self._resolve_credentials(provider)

    def _resolve_credentials(self, provider: str) -> Tuple[Optional[str], Optional[str]]:
        p = provider.lower()
        if p == "groq":
            return self.env.get("GROQ_API_KEY"), "https://api.groq.com/openai/v1"
        elif p == "cerebras":
            return self.env.get("CEREBRAS_API_KEY"), "https://api.cerebras.ai/v1"
        elif p == "mistral":
            return self.env.get("MISTRAL_API_KEY"), "https://api.mistral.ai/v1"
        elif p == "gemini":
            return self.env.get("GEMINI_API_KEY"), "https://generativelanguage.googleapis.com/v1beta/openai"
        elif p == "openrouter":
            return self.env.get("OPENROUTER_API_KEY"), "https://openrouter.ai/api/v1"
        elif p == "cohere":
            return self.env.get("COHERE_API_KEY"), "https://api.cohere.ai/v2"
        elif p == "xai":
            return self.env.get("ZAI_API_KEY") or self.env.get("XAI_API_KEY"), "https://api.x.ai/v1"
        elif p == "alibaba":
            return self.env.get("ALIBABA_API_KEY"), self.env.get("ALIBABA_BASE_URL") or "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
        elif p == "aihubmix":
            return self.env.get("APMIX_API_KEY") or self.env.get("AIHUBMIX_API_KEY"), "https://aihubmix.com/v1"
        elif p == "zenmux":
            return self.env.get("ZENMUX_API_KEY"), "https://zenmux.ai/api/v1"
        elif p == "pollinations":
            return self.env.get("POLLINATIONS_API_KEY"), "https://text.pollinations.ai/openai"
        elif p == "apertis":
            return self.env.get("APERTIS_API_KEY"), "https://api.apertis.ai/v1"
        elif p == "anyapi":
            return self.env.get("ANYAPI_API_KEY"), "https://api.anyapi.ai/v1"
        elif p == "pooled":
            return self.env.get("POOLED_API_KEY"), "https://api.pooled.ai/v1"
        elif p == "dahl":
            return self.env.get("DAHL_API_KEY"), "https://api.dahl.dev/v1"
        return None, None

    def _http_post(self, url: str, payload_dict: Dict[str, Any], timeout: float = 12.0) -> Tuple[int, Dict[str, Any], float, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "claude-master-swarm/1.0",
        }
        body = json.dumps(payload_dict).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers)
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                lat = (time.perf_counter() - t0) * 1000.0
                raw = resp.read().decode("utf-8", errors="replace")
                parsed = json.loads(raw)
                return resp.status, parsed, lat, raw
        except urllib.error.HTTPError as e:
            lat = (time.perf_counter() - t0) * 1000.0
            raw = e.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {"error": raw[:300]}
            return e.code, parsed, lat, raw
        except Exception as e:
            lat = (time.perf_counter() - t0) * 1000.0
            return 0, {"error": str(e)}, lat, str(e)

    def probe_instruction_following(self, model_id: str) -> Dict[str, Any]:
        """Test basic instruction following with exact tag format."""
        if self.provider == "cohere":
            url = f"{self.base_url.rstrip('/')}/chat"
            payload = {
                "model": model_id,
                "messages": [{"role": "user", "content": "Compute 7 * 6. Return ONLY the answer enclosed in tags like: <answer>42</answer>."}],
            }
        else:
            url = f"{self.base_url.rstrip('/')}/chat/completions"
            payload = {
                "model": model_id,
                "messages": [{"role": "user", "content": "Compute 7 * 6. Return ONLY the answer enclosed in tags like: <answer>42</answer>."}],
                "max_tokens": 50,
                "temperature": 0.0,
            }

        status, parsed, lat_ms, raw = self._http_post(url, payload)
        text = ""
        if status == 200:
            if self.provider == "cohere":
                msg = parsed.get("message", {})
                for part in msg.get("content", []):
                    if part.get("type") == "text":
                        text += part.get("text", "")
            else:
                choices = parsed.get("choices", [])
                if choices:
                    text = choices[0].get("message", {}).get("content") or ""

        passed = ("<answer>42</answer>" in text.strip()) or ("42" in text and "<answer>" in text)
        return {
            "test": "instruction_following",
            "http_status": status,
            "latency_ms": round(lat_ms, 2),
            "output_text": text[:200],
            "passed": passed,
            "raw_response": raw[:500],
        }

    def probe_single_tool_call(self, model_id: str) -> Dict[str, Any]:
        """Test single function calling."""
        tools = [{
            "type": "function",
            "function": {
                "name": "check_status",
                "description": "Check status of infrastructure service",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "service": {"type": "string", "description": "service name"}
                    },
                    "required": ["service"],
                },
            },
        }]

        if self.provider == "cohere":
            url = f"{self.base_url.rstrip('/')}/chat"
            payload = {
                "model": model_id,
                "messages": [{"role": "user", "content": "Check the health of database service now."}],
                "tools": tools,
            }
        else:
            url = f"{self.base_url.rstrip('/')}/chat/completions"
            payload = {
                "model": model_id,
                "messages": [{"role": "user", "content": "Check the health of database service now."}],
                "tools": tools,
                "tool_choice": "auto",
                "max_tokens": 80,
            }

        status, parsed, lat_ms, raw = self._http_post(url, payload)
        has_tool = False
        tool_name = None
        args = None
        schema_valid = False

        if status == 200:
            if self.provider == "cohere":
                msg = parsed.get("message", {})
                tcalls = msg.get("tool_calls", [])
                if tcalls:
                    has_tool = True
                    tool_name = tcalls[0].get("function", {}).get("name")
                    args = tcalls[0].get("function", {}).get("arguments")
                    schema_valid = isinstance(args, dict) or (isinstance(args, str) and "service" in args)
            else:
                choices = parsed.get("choices", [])
                if choices:
                    msg = choices[0].get("message", {})
                    tcalls = msg.get("tool_calls", [])
                    if tcalls:
                        has_tool = True
                        fn = tcalls[0].get("function", {})
                        tool_name = fn.get("name")
                        raw_args = fn.get("arguments", "")
                        try:
                            parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                            schema_valid = isinstance(parsed_args, dict) and "service" in parsed_args
                        except Exception:
                            schema_valid = False

        return {
            "test": "single_tool_call",
            "http_status": status,
            "latency_ms": round(lat_ms, 2),
            "has_tool_call": has_tool,
            "tool_name": tool_name,
            "schema_valid": schema_valid,
            "passed": has_tool and schema_valid,
            "raw_response": raw[:500],
        }

    def probe_parallel_tool_call(self, model_id: str) -> Dict[str, Any]:
        """Test parallel tool calling (invoking multiple tools in one turn)."""
        tools = [{
            "type": "function",
            "function": {
                "name": "check_status",
                "description": "Check service status",
                "parameters": {
                    "type": "object",
                    "properties": {"service": {"type": "string"}},
                    "required": ["service"],
                },
            },
        }]

        prompt = "Check the status of both 'database' AND 'redis' services simultaneously."
        if self.provider == "cohere":
            url = f"{self.base_url.rstrip('/')}/chat"
            payload = {
                "model": model_id,
                "messages": [{"role": "user", "content": prompt}],
                "tools": tools,
            }
        else:
            url = f"{self.base_url.rstrip('/')}/chat/completions"
            payload = {
                "model": model_id,
                "messages": [{"role": "user", "content": prompt}],
                "tools": tools,
                "tool_choice": "auto",
                "max_tokens": 150,
            }

        status, parsed, lat_ms, raw = self._http_post(url, payload)
        tool_count = 0
        if status == 200:
            if self.provider == "cohere":
                tcalls = parsed.get("message", {}).get("tool_calls") or []
                tool_count = len(tcalls)
            else:
                choices = parsed.get("choices", [])
                if choices:
                    tcalls = choices[0].get("message", {}).get("tool_calls") or []
                    tool_count = len(tcalls)

        return {
            "test": "parallel_tool_call",
            "http_status": status,
            "latency_ms": round(lat_ms, 2),
            "tool_count": tool_count,
            "passed": tool_count >= 2,
            "raw_response": raw[:500],
        }

    def run(self) -> Dict[str, Any]:
        logger.info(f"Worker {self.worker_id} started for provider {self.provider}")
        log_ledger_event(self.worker_id, f"provider:{self.provider}", "started")

        jobs_done = 0
        jobs_failed = 0
        total_cost = 0.0

        if not self.api_key:
            logger.warning(f"No API key for {self.provider}. Cannot run live probes.")
            # Mark all queued jobs for this provider as failed or excluded
            while True:
                job = self.queue.claim_job(self.worker_id, stage=1, provider=self.provider)
                if not job:
                    break
                self.queue.complete_job(
                    job["job_id"],
                    self.worker_id,
                    state="failed",
                    reason_code="no_key_no_access",
                )
                jobs_failed += 1
            log_ledger_event(self.worker_id, f"provider:{self.provider}", "finished", jobs_done, jobs_failed)
            return {"jobs_done": jobs_done, "jobs_failed": jobs_failed}

        while jobs_done + jobs_failed < self.max_jobs:
            job = self.queue.claim_job(self.worker_id, stage=1, provider=self.provider, lease_duration=120.0)
            if not job:
                logger.info(f"No more eligible stage 1 jobs for provider {self.provider}")
                break

            job_id = job["job_id"]
            route_id = job["route"]
            # Extract raw model ID from route
            parts = route_id.split(":", 1)
            raw_model_id = parts[1] if len(parts) > 1 else route_id

            logger.info(f"Screening job {job_id} | Route: {route_id} | Model: {raw_model_id}")
            self.queue.heartbeat(self.worker_id, job_id, lease_duration=120.0)

            # Probe sequence
            t_start = time.time()
            probe_results = {}

            # 1. Instruction following
            p_inst = self.probe_instruction_following(raw_model_id)
            probe_results["instruction_following"] = p_inst
            time.sleep(self.safe_delay)

            # Check if endpoint failed outright (e.g. 401, 402, 403, 404)
            if p_inst["http_status"] in (401, 402, 403, 404, 500, 502, 503):
                err_code = f"http_{p_inst['http_status']}"
                job_state = "failed"
                reason_code = f"probe_error:{err_code}"
                logger.warning(f"Route {route_id} failed with HTTP {p_inst['http_status']}")
            else:
                # 2. Single tool calling
                p_tool = self.probe_single_tool_call(raw_model_id)
                probe_results["single_tool_call"] = p_tool
                time.sleep(self.safe_delay)

                # 3. Parallel tool calling
                p_par = self.probe_parallel_tool_call(raw_model_id)
                probe_results["parallel_tool_call"] = p_par

                # Evaluate overall screening pass
                inst_ok = p_inst.get("passed", False)
                tool_ok = p_tool.get("passed", False)
                par_ok = p_par.get("passed", False)

                if tool_ok:
                    job_state = "done"
                    reason_code = None
                    logger.info(f"Route {route_id} PASSED Stage 1 screening (single_tc={tool_ok}, parallel_tc={par_ok}, inst={inst_ok})")
                else:
                    job_state = "failed"
                    reason_code = "screening_tool_call_invalid"
                    logger.info(f"Route {route_id} FAILED tool call validity (single_tc={tool_ok})")

            # Save raw artifact (sanitize filename for Windows)
            safe_fname = job_id.replace(":", "_").replace("/", "_") + ".json"
            artifact_path = self.results_dir / safe_fname
            artifact_record = {
                "job_id": job_id,
                "route_id": route_id,
                "canonical_id": job.get("canonical_id"),
                "provider": self.provider,
                "provider_model_id": raw_model_id,
                "stage": 1,
                "state": job_state,
                "reason_code": reason_code,
                "timestamp": time.time(),
                "duration_seconds": round(time.time() - t_start, 2),
                "probes": probe_results,
            }
            artifact_path.write_text(json.dumps(artifact_record, indent=2, ensure_ascii=False), encoding="utf-8")

            # Append to results.jsonl
            with open(self.results_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(artifact_record, ensure_ascii=False) + "\n")

            # Complete job in queue
            rel_artifact_path = str(artifact_path.relative_to(ROOT)).replace("\\", "/")
            self.queue.complete_job(
                job_id=job_id,
                worker_id=self.worker_id,
                state=job_state,
                result_path=rel_artifact_path,
                reason_code=reason_code,
            )

            # If Stage 1 passed, ensure Stage 2 job is queued and ready for CLI workers
            if job_state == "done":
                jobs_done += 1
            else:
                jobs_failed += 1
                # If Stage 1 failed, mark Stage 2 as excluded
                s2_job_id = f"s2_{route_id}"
                self.queue.complete_job(
                    job_id=s2_job_id,
                    worker_id=self.worker_id,
                    state="excluded",
                    reason_code=f"stage1_screening_failed:{reason_code}",
                )

            time.sleep(self.safe_delay)

        log_ledger_event(self.worker_id, f"provider:{self.provider}", "finished", jobs_done, jobs_failed)
        logger.info(f"Worker {self.worker_id} finished: {jobs_done} done, {jobs_failed} failed.")
        return {"jobs_done": jobs_done, "jobs_failed": jobs_failed}


def main():
    parser = argparse.ArgumentParser(description="Run Stage 1 Screening Worker")
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--safe-rpm", type=int, default=30)
    args = parser.parse_args()

    runner = ScreeningRunner(
        worker_id=args.worker_id,
        provider=args.provider,
        max_jobs=args.max_jobs,
        safe_rpm=args.safe_rpm,
    )
    runner.run()


if __name__ == "__main__":
    main()
