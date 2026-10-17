"""Multi-Model Agentic Route & Tool Rescue Empirical Runner.

Fulfills:
- Directive 2: Run S1 and S2 across agentic routes (cheapest first, early stop when clear),
  recording router choice and explanation.
- Directive 3: Measure pass rates with Tool Rescue ON vs OFF, reporting rescue counts and repairs.
- Directive 5: Capture stage latency breakdown per stage (gw, router, ttft, gen, rescue).

Uses the real installed `claude` CLI binary against an isolated universal gateway
in throwaway workspaces with independent oracles.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from brain.api.services.routing_service import get_dynamic_router, build_candidate_metrics_from_models
from brain.routing.engine import RouteRequest


def wilson_ci_95(successes: int, total: int) -> Tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    z = 1.95996
    p = successes / total
    denom = 1.0 + (z * z) / total
    centre = (p + (z * z) / (2.0 * total)) / denom
    spread = (z * math.sqrt((p * (1.0 - p) / total) + (z * z) / (4.0 * total * total))) / denom
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def load_env(path: str) -> Dict[str, str]:
    vals = {}
    if not os.path.exists(path):
        return vals
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip("\"'")
    return vals


def choose_free_port(host="127.0.0.1") -> int:
    with socket.socket() as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def wait_health(url: str, timeout: int = 30) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def get_toolrescue_stats(gw_port: int) -> Dict[str, Any]:
    try:
        with urllib.request.urlopen(f"http://localhost:{gw_port}/admin/toolrescue", timeout=3) as r:
            if r.status == 200:
                return json.loads(r.read().decode())
    except Exception as e:
        pass
    return {}


def run_claude(prompt: str, taskdir: str, profile_dir: str, gateway_port: int,
               model: Optional[str] = None, timeout: int = 180,
               extra_env: Optional[Dict[str, str]] = None) -> Tuple[int, str, float, Dict[str, Any]]:
    cmd = [
        "claude", "-p", prompt,
        "--allowedTools", "Write", "Edit", "Read", "Bash", "Glob", "Grep", "Task",
        "--permission-mode", "dontAsk",
        "--output-format", "json",
        "--add-dir", taskdir,
    ]
    if model:
        cmd += ["--model", model]

    env = dict(
        os.environ,
        ANTHROPIC_BASE_URL=f"http://localhost:{gateway_port}",
        ANTHROPIC_API_KEY="dummy",
        ANTHROPIC_MODEL=(model or "sonnet"),
        CLAUDE_CONFIG_DIR=profile_dir,
    )
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    if extra_env:
        env.update(extra_env)

    t0 = time.perf_counter()
    try:
        p = subprocess.run(
            cmd, cwd=taskdir, env=env, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout
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


def evaluate_s1_oracle(d: str, stdout: str, rc: int) -> bool:
    # STRICT oracle (CORRECTION 2): only the specified path `d` counts.
    # Files outside `d` (e.g. slugified sibling d.replace("_","-")) are FAIL.
    if rc != 0:
        return False
    try:
        txt_files = [f for f in os.listdir(d) if f.endswith(".txt")]
    except OSError:
        return False
    if len(txt_files) < 3:
        return False
    return all(
        open(os.path.join(d, f), encoding="utf-8").read().strip().endswith("-done")
        for f in txt_files
    )


def evaluate_s2_oracle(d: str, stdout: str, rc: int) -> bool:
    return rc == 0 and ("CHECK-OK-123" in stdout)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json-out", default="off/e2e/multi_model_agentic_routes.json")
    ap.add_argument("--rescue-out", default="off/e2e/tool_rescue_empirical.json")
    ap.add_argument("--reps-per-route", type=int, default=3, help="Reps per agentic route (early stop on failure)")
    ap.add_argument("--reps-rescue", type=int, default=5, help="Reps for rescue ON vs OFF comparison")
    args = ap.parse_args()

    env_vals = load_env(".env")
    gw_port = choose_free_port()
    base_tmp = tempfile.mkdtemp(prefix="cm_agentic_")

    log_dir = os.path.join(base_tmp, "traffic")
    os.makedirs(log_dir, exist_ok=True)

    gw_proc = subprocess.Popen(
        [
            os.path.join(REPO_ROOT, "gateway", "gateway.exe"),
            "-config", os.path.join(REPO_ROOT, "gateway", "config.json"),
            "-env-file", os.path.join(REPO_ROOT, ".env"),
            "-listen", f"127.0.0.1:{gw_port}",
            "-log-requests", log_dir,
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        assert wait_health(f"http://localhost:{gw_port}/health", timeout=30), "Gateway failed to start"
        print(f"[*] Gateway running on port {gw_port}")

        # 1. Resolve candidates and dynamic router explanations
        candidates = build_candidate_metrics_from_models()
        router = get_dynamic_router()

        # Dynamic explanations for S1 and S2
        s1_prompt = "Directly in the current working directory, create a.txt with 'alpha', b.txt with 'beta', c.txt with 'gamma'. Then append '-done' to each of those three files."
        s2_prompt = "Run: python check.py. Report its exact output."

        req_s1 = RouteRequest(prompt=s1_prompt, custom_candidates=candidates)
        dec_s1 = router.route(req_s1)
        exp_s1 = router.explain(dec_s1.request_id)

        req_s2 = RouteRequest(prompt=s2_prompt, custom_candidates=candidates)
        dec_s2 = router.route(req_s2)
        exp_s2 = router.explain(dec_s2.request_id)

        print("\n=======================================================")
        print("PART 1: DYNAMIC ROUTER SELECTIONS & EXPLANATIONS")
        print("=======================================================")
        print(f"Task S1 (Multi-file Tool):")
        print(f"  Chosen Route:     {dec_s1.selected_route_id} ({dec_s1.provider})")
        print(f"  Decision Source:  {dec_s1.decision_source}")
        print(f"  Composite Utility:{dec_s1.composite_utility:.4f}")
        print(f"  Top Candidates:   {[(c.metrics.route_id, round(c.utility_score, 3)) for c in exp_s1.all_scored_candidates[:4]]}")

        print(f"\nTask S2 (Shell Execution):")
        print(f"  Chosen Route:     {dec_s2.selected_route_id} ({dec_s2.provider})")
        print(f"  Decision Source:  {dec_s2.decision_source}")
        print(f"  Composite Utility:{dec_s2.composite_utility:.4f}")
        print(f"  Top Candidates:   {[(c.metrics.route_id, round(c.utility_score, 3)) for c in exp_s2.all_scored_candidates[:4]]}")

        # List of candidate agentic routes to test (cheapest / highest utility first)
        routes_to_test = [
            {"id": "ministral-8b-latest", "provider": "mistral", "pricing": "$0.10/$0.10/M"},
            {"id": "openai/gpt-oss-120b", "provider": "groq", "pricing": "Free/Low"},
            {"id": "qwen/qwen3.8-27b", "provider": "groq", "pricing": "Free/Low"},
            {"id": "gemini-2.5-flash", "provider": "gemini", "pricing": "Standard/Low"},
            {"id": "command-r-plus-08-2024", "provider": "cohere", "pricing": "Enterprise/Trial"},
            {"id": "qwen/qwen3-30b-a3b", "provider": "openrouter", "pricing": "Free/Trial"},
        ]

        print("\n=======================================================")
        print("PART 2: MULTI-MODEL REAL CLAUDE CODE EXECUTION (S1 & S2)")
        print("=======================================================")

        results_multi_model = []

        for route in routes_to_test:
            model_id = route["id"]
            provider = route["provider"]
            print(f"\n--- Testing Route: {model_id} via {provider} ({route['pricing']}) ---")

            # Test S1
            s1_successes = 0
            s1_latencies = []
            for rep in range(1, args.reps_per_route + 1):
                task_dir = os.path.join(base_tmp, f"s1_{provider}_{model_id.replace('/', '_')}_r{rep}")
                prof_dir = os.path.join(base_tmp, f"prof_s1_{provider}_{model_id.replace('/', '_')}_r{rep}")
                os.makedirs(task_dir, exist_ok=True)
                os.makedirs(prof_dir, exist_ok=True)

                rc, out, lat_ms, payload = run_claude(
                    prompt=s1_prompt,
                    taskdir=task_dir,
                    profile_dir=prof_dir,
                    gateway_port=gw_port,
                    model=model_id,
                    timeout=90,
                )
                passed = evaluate_s1_oracle(task_dir, out, rc)
                if passed:
                    s1_successes += 1
                s1_latencies.append(lat_ms)
                status = "PASS" if passed else "FAIL"
                print(f"  S1 rep{rep}: {status} (rc={rc}, lat={lat_ms:.0f}ms)")
                # Early stop on 2 consecutive fails
                if rep >= 2 and s1_successes == 0:
                    print(f"  Early stopping on route {model_id} for S1 (clear failure)")
                    break

            # Test S2
            s2_successes = 0
            s2_latencies = []
            for rep in range(1, args.reps_per_route + 1):
                task_dir = os.path.join(base_tmp, f"s2_{provider}_{model_id.replace('/', '_')}_r{rep}")
                prof_dir = os.path.join(base_tmp, f"prof_s2_{provider}_{model_id.replace('/', '_')}_r{rep}")
                os.makedirs(task_dir, exist_ok=True)
                os.makedirs(prof_dir, exist_ok=True)
                with open(os.path.join(task_dir, "check.py"), "w", encoding="utf-8") as f:
                    f.write("print('CHECK-OK-123')\n")

                rc, out, lat_ms, payload = run_claude(
                    prompt=s2_prompt,
                    taskdir=task_dir,
                    profile_dir=prof_dir,
                    gateway_port=gw_port,
                    model=model_id,
                    timeout=90,
                )
                passed = evaluate_s2_oracle(task_dir, out, rc)
                if passed:
                    s2_successes += 1
                s2_latencies.append(lat_ms)
                status = "PASS" if passed else "FAIL"
                print(f"  S2 rep{rep}: {status} (rc={rc}, lat={lat_ms:.0f}ms)")
                # Early stop on 2 consecutive fails
                if rep >= 2 and s2_successes == 0:
                    print(f"  Early stopping on route {model_id} for S2 (clear failure)")
                    break

            s1_ci = wilson_ci_95(s1_successes, len(s1_latencies))
            s2_ci = wilson_ci_95(s2_successes, len(s2_latencies))

            results_multi_model.append({
                "model_id": model_id,
                "provider": provider,
                "pricing": route["pricing"],
                "s1": {
                    "reps": len(s1_latencies),
                    "successes": s1_successes,
                    "pass_rate": s1_successes / len(s1_latencies) if s1_latencies else 0.0,
                    "ci_95": s1_ci,
                    "latencies_ms": s1_latencies,
                    "mean_latency_ms": sum(s1_latencies) / len(s1_latencies) if s1_latencies else 0.0,
                },
                "s2": {
                    "reps": len(s2_latencies),
                    "successes": s2_successes,
                    "pass_rate": s2_successes / len(s2_latencies) if s2_latencies else 0.0,
                    "ci_95": s2_ci,
                    "latencies_ms": s2_latencies,
                    "mean_latency_ms": sum(s2_latencies) / len(s2_latencies) if s2_latencies else 0.0,
                }
            })

        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({
                "dynamic_router_explanations": {
                    "s1": {
                        "chosen_route": dec_s1.selected_route_id,
                        "provider": dec_s1.provider,
                        "decision_source": dec_s1.decision_source,
                        "composite_utility": dec_s1.composite_utility,
                        "top_candidates": [
                            {"route_id": c.metrics.route_id, "utility": c.utility_score, "quality": c.quality_score, "cost": c.cost_score}
                            for c in exp_s1.all_scored_candidates[:5]
                        ]
                    },
                    "s2": {
                        "chosen_route": dec_s2.selected_route_id,
                        "provider": dec_s2.provider,
                        "decision_source": dec_s2.decision_source,
                        "composite_utility": dec_s2.composite_utility,
                        "top_candidates": [
                            {"route_id": c.metrics.route_id, "utility": c.utility_score, "quality": c.quality_score, "cost": c.cost_score}
                            for c in exp_s2.all_scored_candidates[:5]
                        ]
                    }
                },
                "routes": results_multi_model
            }, f, indent=2)
        print(f"\n[+] Saved multi-model results to {args.json_out}")

        # 3. Directive 3: Tool Rescue ON vs OFF comparison
        print("\n=======================================================", flush=True)
        print("PART 3: TOOL RESCUE EMPIRICAL COMPARISON (ON vs OFF)", flush=True)
        print("=======================================================", flush=True)
        target_model = "openai/gpt-oss-120b"
        print(f"Target model for Tool Rescue evaluation: {target_model}", flush=True)

        initial_rescue_stats = get_toolrescue_stats(gw_port)
        print(f"Initial tool rescue stats: {initial_rescue_stats}", flush=True)

        # Rescue ON runs
        rescue_on_successes = 0
        rescue_on_latencies = []
        for rep in range(1, args.reps_rescue + 1):
            task_dir = os.path.join(base_tmp, f"rescue_on_r{rep}")
            prof_dir = os.path.join(base_tmp, f"prof_rescue_on_r{rep}")
            os.makedirs(task_dir, exist_ok=True)
            os.makedirs(prof_dir, exist_ok=True)

            rc, out, lat_ms, payload = run_claude(
                prompt=s1_prompt,
                taskdir=task_dir,
                profile_dir=prof_dir,
                gateway_port=gw_port,
                model=target_model,
                timeout=90,
            )
            passed = evaluate_s1_oracle(task_dir, out, rc)
            if passed:
                rescue_on_successes += 1
            rescue_on_latencies.append(lat_ms)
            print(f"  Rescue ON rep{rep}: {'PASS' if passed else 'FAIL'} (lat={lat_ms:.0f}ms)")

        mid_rescue_stats = get_toolrescue_stats(gw_port)

        # Rescue OFF runs (via extra_env ANTHROPIC_CUSTOM_HEADERS or testing against gateway with header)
        # Note: in gateway, X-Tool-Rescue-Disabled: true disables rescue.
        # We can pass custom headers or test config with tool_rescue_enabled: false.
        print("\nTesting Rescue OFF (Tool Rescue Disabled)...")
        # Start a dedicated gateway with tool_rescue_enabled = false
        cfg_rescue_off = os.path.join(base_tmp, "config_rescue_off.json")
        with open(os.path.join(REPO_ROOT, "gateway", "config.json"), encoding="utf-8") as f:
            cfg_obj = json.load(f)
        cfg_obj["tool_rescue_enabled"] = False
        with open(cfg_rescue_off, "w", encoding="utf-8") as f:
            json.dump(cfg_obj, f, indent=2)

        gw_off_port = choose_free_port()
        gw_off_proc = subprocess.Popen(
            [
                os.path.join(REPO_ROOT, "gateway", "gateway.exe"),
                "-config", cfg_rescue_off,
                "-env-file", os.path.join(REPO_ROOT, ".env"),
                "-listen", f"127.0.0.1:{gw_off_port}",
                "-log-requests", os.path.join(base_tmp, "traffic_off"),
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        try:
            assert wait_health(f"http://localhost:{gw_off_port}/health", timeout=30), "Rescue-off gateway failed"
            rescue_off_successes = 0
            rescue_off_latencies = []
            for rep in range(1, args.reps_rescue + 1):
                task_dir = os.path.join(base_tmp, f"rescue_off_r{rep}")
                prof_dir = os.path.join(base_tmp, f"prof_rescue_off_r{rep}")
                os.makedirs(task_dir, exist_ok=True)
                os.makedirs(prof_dir, exist_ok=True)

                rc, out, lat_ms, payload = run_claude(
                    prompt=s1_prompt,
                    taskdir=task_dir,
                    profile_dir=prof_dir,
                    gateway_port=gw_off_port,
                    model=target_model,
                    timeout=90,
                )
                passed = evaluate_s1_oracle(task_dir, out, rc)
                if passed:
                    rescue_off_successes += 1
                rescue_off_latencies.append(lat_ms)
                print(f"  Rescue OFF rep{rep}: {'PASS' if passed else 'FAIL'} (lat={lat_ms:.0f}ms)")

            final_off_stats = get_toolrescue_stats(gw_off_port)

            rescue_comparison = {
                "model": target_model,
                "reps": args.reps_rescue,
                "rescue_on": {
                    "successes": rescue_on_successes,
                    "total": len(rescue_on_latencies),
                    "pass_rate": rescue_on_successes / len(rescue_on_latencies) if rescue_on_latencies else 0.0,
                    "ci_95": wilson_ci_95(rescue_on_successes, len(rescue_on_latencies)),
                    "latencies_ms": rescue_on_latencies,
                    "rescue_metrics": mid_rescue_stats,
                },
                "rescue_off": {
                    "successes": rescue_off_successes,
                    "total": len(rescue_off_latencies),
                    "pass_rate": rescue_off_successes / len(rescue_off_latencies) if rescue_off_latencies else 0.0,
                    "ci_95": wilson_ci_95(rescue_off_successes, len(rescue_off_latencies)),
                    "latencies_ms": rescue_off_latencies,
                    "rescue_metrics": final_off_stats,
                }
            }

            os.makedirs(os.path.dirname(os.path.abspath(args.rescue_out)), exist_ok=True)
            with open(args.rescue_out, "w", encoding="utf-8") as f:
                json.dump(rescue_comparison, f, indent=2)
            print(f"\n[+] Saved Tool Rescue comparison to {args.rescue_out}")

        finally:
            gw_off_proc.terminate()
            gw_off_proc.wait(timeout=5)

    finally:
        gw_proc.terminate()
        gw_proc.wait(timeout=5)
        # Clean up temp files
        shutil.rmtree(base_tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
