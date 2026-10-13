"""eval_runner.py — Real Model Evaluation & Empirical Benchmark Runner.

Executes empirical task probes against active universal gateway routes.
Measures:
- Empirical TTFT (Time To First Token) in ms
- Generation throughput (tokens/sec)
- Success rate per task type with sample size (N), 95% Wilson confidence intervals, and timestamps
- Saves datasets to:
    - data/evals/results.json (detailed probe logs)
    - data/evals/leaderboard.json (aggregated empirical leaderboard)
- Strictly enforces zero API key logging.
"""

from __future__ import annotations

import base64
import datetime
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVALS_DIR = os.path.join(REPO_ROOT, "data", "evals")
TASKS_PATH = os.path.join(EVALS_DIR, "tasks.json")
RESULTS_PATH = os.path.join(EVALS_DIR, "results.json")
LEADERBOARD_PATH = os.path.join(EVALS_DIR, "leaderboard.json")


def ensure_gateway(gateway_url: str = "http://127.0.0.1:8080") -> Optional[subprocess.Popen]:
    """Ensure universal gateway is running; spawn managed subprocess if not."""
    try:
        with urllib.request.urlopen(f"{gateway_url.rstrip('/')}/health", timeout=1) as resp:
            if resp.status == 200:
                return None
    except Exception:
        pass

    gw_exe = os.path.join(REPO_ROOT, "gateway", "gateway.exe")
    cfg_file = os.path.join(REPO_ROOT, "gateway", "config.json")
    if not os.path.exists(gw_exe):
        raise FileNotFoundError(f"Gateway binary not found: {gw_exe}")

    proc = subprocess.Popen([gw_exe, "-config", cfg_file], cwd=REPO_ROOT)
    for _ in range(30):
        time.sleep(0.5)
        try:
            with urllib.request.urlopen(f"{gateway_url.rstrip('/')}/health", timeout=1) as resp:
                if resp.status == 200:
                    print(f"Gateway started successfully (PID {proc.pid})")
                    return proc
        except Exception:
            pass

    return proc


def wilson_score_interval(successes: int, total: int, confidence: float = 0.95) -> Tuple[float, float]:
    """Calculate the Wilson score confidence interval for a binomial proportion.

    Handles edge cases (0, total) smoothly without undefined limits.
    """
    if total <= 0 or successes < 0:
        return 0.0, 0.0

    successes = min(successes, total)

    # z-value for confidence level (1.95996 for 95%)
    z = 1.95996 if abs(confidence - 0.95) < 1e-4 else 1.64485
    p_hat = successes / total
    denominator = 1.0 + (z ** 2) / total
    centre_adjusted_probability = p_hat + (z ** 2) / (2.0 * total)
    variance_term = (p_hat * (1.0 - p_hat) + (z ** 2) / (4.0 * total)) / total
    adjusted_standard_deviation = math.sqrt(max(0.0, variance_term))

    lower = (centre_adjusted_probability - z * adjusted_standard_deviation) / denominator
    upper = (centre_adjusted_probability + z * adjusted_standard_deviation) / denominator

    return max(0.0, float(round(lower, 4))), min(1.0, float(round(upper, 4)))


def post_gateway(url: str, payload: dict, timeout: int = 60) -> Tuple[int, dict, float]:
    """Post request to universal gateway and return (status_code, json_body, round_trip_ms)."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"}
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return resp.status, body, latency_ms


def measure_ttft_and_throughput(gateway_url: str, model: str, max_tokens: int = 80) -> Dict[str, Any]:
    """Empirically measure TTFT (ms) and generation throughput (tokens/sec) via streaming."""
    chat_url = f"{gateway_url.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "List the prime numbers between 1 and 30 separated by commas."}],
        "stream": True,
        "max_tokens": max_tokens
    }
    req = urllib.request.Request(
        chat_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )

    t0 = time.perf_counter()
    first_token_time = None
    last_token_time = None
    token_count = 0
    full_text_chunks = []

    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            for line in resp:
                raw_line = line.decode("utf-8").strip()
                if not raw_line or raw_line.startswith(":") or raw_line == "data: [DONE]":
                    continue
                if raw_line.startswith("data: "):
                    now = time.perf_counter()
                    if first_token_time is None:
                        first_token_time = now
                    try:
                        chunk = json.loads(raw_line[6:])
                        choices = chunk.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content") or delta.get("reasoning")
                            if content:
                                token_count += 1
                                full_text_chunks.append(content)
                                last_token_time = now
                    except Exception:
                        pass
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "ttft_ms": 0.0,
            "throughput_tok_s": 0.0,
            "token_count": 0
        }

    t_end = time.perf_counter()
    if first_token_time is None:
        ttft_ms = (t_end - t0) * 1000.0
        gen_duration = 0.0
        throughput = 0.0
    else:
        ttft_ms = (first_token_time - t0) * 1000.0
        gen_duration = (last_token_time - first_token_time) if (last_token_time and last_token_time > first_token_time) else (t_end - first_token_time)
        throughput = (token_count / gen_duration) if gen_duration > 0.005 else (token_count / 0.1)

    return {
        "success": token_count > 0 or first_token_time is not None,
        "ttft_ms": round(ttft_ms, 2),
        "throughput_tok_s": round(throughput, 2),
        "token_count": token_count,
        "duration_s": round(t_end - t0, 3)
    }


def evaluate_tool_call_validity(gateway_url: str, model: str, task: dict) -> Dict[str, Any]:
    """Execute and validate tool_call_validity task."""
    chat_url = f"{gateway_url.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": task["prompt"]}],
        "tools": task["tools"],
        "tool_choice": "auto",
        "max_tokens": 250
    }

    try:
        status, body, latency_ms = post_gateway(chat_url, payload)
        choices = body.get("choices", [])
        if not choices:
            return {"task_id": task["task_id"], "passed": False, "score": 0.0, "latency_ms": latency_ms, "error": "No choices returned"}

        msg = choices[0].get("message", {})
        tool_calls = msg.get("tool_calls", [])
        if not tool_calls:
            # Check if model returned tool call inside content as json
            content = msg.get("content") or ""
            return {"task_id": task["task_id"], "passed": False, "score": 0.0, "latency_ms": latency_ms, "error": f"No tool calls found. Content: {content[:100]}"}

        first_call = tool_calls[0]
        func = first_call.get("function", {})
        func_name = func.get("name", "")
        args_raw = func.get("arguments", "{}")
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
        except Exception as e:
            return {"task_id": task["task_id"], "passed": False, "score": 0.2, "latency_ms": latency_ms, "error": f"Malformed JSON arguments: {e}"}

        val = task["validation"]
        if func_name != val["expected_function"]:
            return {"task_id": task["task_id"], "passed": False, "score": 0.3, "latency_ms": latency_ms, "error": f"Expected function {val['expected_function']}, got {func_name}"}

        # Check expected arguments
        expected_args = val.get("expected_args", {})
        matched_keys = 0
        total_keys = len(expected_args)
        for k, v in expected_args.items():
            if k in args:
                if str(args[k]).lower() == str(v).lower():
                    matched_keys += 1
                elif isinstance(v, (int, float)) and isinstance(args[k], (int, float)) and abs(args[k] - v) < 1e-4:
                    matched_keys += 1

        if "state_match" in val:
            total_keys += 1
            if args.get("state") in val["state_match"]:
                matched_keys += 1

        if "attendees_contains" in val:
            total_keys += len(val["attendees_contains"])
            attendees = args.get("attendees", [])
            for att in val["attendees_contains"]:
                if att in attendees:
                    matched_keys += 1

        passed = matched_keys == total_keys or (matched_keys / total_keys >= 0.75)
        score = matched_keys / total_keys if total_keys > 0 else 1.0

        return {
            "task_id": task["task_id"],
            "passed": passed,
            "score": round(score, 2),
            "latency_ms": round(latency_ms, 2),
            "tool_call": {"name": func_name, "args": args}
        }
    except Exception as e:
        return {"task_id": task["task_id"], "passed": False, "score": 0.0, "latency_ms": 0.0, "error": str(e)}


def evaluate_multi_step_loop(gateway_url: str, model: str, task: dict) -> Dict[str, Any]:
    """Execute chained multi-step tool calls loop."""
    chat_url = f"{gateway_url.rstrip('/')}/v1/chat/completions"
    messages = [{"role": "user", "content": task["prompt"]}]
    tools = task["tools"]
    steps = task["steps"]
    total_latency_ms = 0.0

    try:
        for step in steps:
            payload = {
                "model": model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                "max_tokens": 300
            }
            status, body, latency_ms = post_gateway(chat_url, payload)
            total_latency_ms += latency_ms

            msg = body["choices"][0]["message"]
            messages.append(msg)
            tool_calls = msg.get("tool_calls", [])
            if not tool_calls:
                return {"task_id": task["task_id"], "passed": False, "score": 0.2, "latency_ms": total_latency_ms, "error": f"Step {step['step_number']} missing tool call"}

            tc = tool_calls[0]
            func_name = tc.get("function", {}).get("name")
            if func_name != step["expected_call"]:
                return {"task_id": task["task_id"], "passed": False, "score": 0.4, "latency_ms": total_latency_ms, "error": f"Expected tool {step['expected_call']}, got {func_name}"}

            # Feed tool response into message history
            tool_res_msg = {
                "role": "tool",
                "tool_call_id": tc.get("id", f"call_step_{step['step_number']}"),
                "content": json.dumps(step["mock_response"])
            }
            messages.append(tool_res_msg)

        # Final turn: synthesize answer
        final_payload = {
            "model": model,
            "messages": messages,
            "max_tokens": 300
        }
        status, final_body, latency_ms = post_gateway(chat_url, final_payload)
        total_latency_ms += latency_ms
        final_content = (final_body["choices"][0]["message"].get("content") or "").lower()

        val = task["validation"]
        must_contain = val.get("final_answer_must_contain", [])
        matches = [kw for kw in must_contain if kw.lower() in final_content]
        passed = len(matches) >= (len(must_contain) * 0.66)

        return {
            "task_id": task["task_id"],
            "passed": passed,
            "score": round(len(matches) / len(must_contain) if must_contain else 1.0, 2),
            "latency_ms": round(total_latency_ms, 2),
            "final_content_preview": final_content[:120]
        }
    except Exception as e:
        return {"task_id": task["task_id"], "passed": False, "score": 0.0, "latency_ms": round(total_latency_ms, 2), "error": str(e)}


def extract_python_code(content: str) -> str:
    """Robustly extract python code from markdown code blocks or raw text."""
    m = re.search(r"```(?:python)?\s*\n(.*?)\n```", content, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"```(?:python)?\s*\n(.*)", content, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).rstrip("`").strip()
    return content.replace("```python", "").replace("```", "").strip()


def evaluate_code_edit(gateway_url: str, model: str, task: dict) -> Dict[str, Any]:
    """Execute code edit generation and test dynamically against real python unit tests."""
    chat_url = f"{gateway_url.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": task["prompt"]}],
        "max_tokens": 800
    }

    try:
        status, body, latency_ms = post_gateway(chat_url, payload)
        content = body["choices"][0]["message"].get("content") or ""

        code = extract_python_code(content)

        # Prepare execution sandbox
        sandbox_scope = {}
        exec(code, sandbox_scope)

        target_sym = task["target_symbol"]
        if target_sym not in sandbox_scope:
            return {"task_id": task["task_id"], "passed": False, "score": 0.2, "latency_ms": latency_ms, "error": f"Symbol {target_sym} not found in generated code"}

        # Compile and execute the real test suite code
        test_scope = {}
        exec(task["test_suite"], test_scope)
        run_tests_fn = test_scope.get("run_tests")
        if not run_tests_fn:
            return {"task_id": task["task_id"], "passed": False, "score": 0.3, "latency_ms": latency_ms, "error": "Test suite missing run_tests function"}

        test_result = run_tests_fn(sandbox_scope[target_sym])
        passed = bool(test_result is True)

        return {
            "task_id": task["task_id"],
            "passed": passed,
            "score": 1.0 if passed else 0.0,
            "latency_ms": round(latency_ms, 2),
            "target_symbol": target_sym
        }
    except Exception as e:
        return {"task_id": task["task_id"], "passed": False, "score": 0.0, "latency_ms": round(latency_ms if 'latency_ms' in locals() else 0.0, 2), "error": str(e)}


def evaluate_reasoning(gateway_url: str, model: str, task: dict) -> Dict[str, Any]:
    """Execute instruction following and reasoning (GSM8k & logic)."""
    chat_url = f"{gateway_url.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": task["prompt"]}],
        "max_tokens": 400
    }

    try:
        status, body, latency_ms = post_gateway(chat_url, payload)
        content = body["choices"][0]["message"].get("content") or ""
        reasoning = body["choices"][0]["message"].get("reasoning") or ""

        val = task["validation"]
        vtype = val.get("type")

        if vtype == "exact_tag":
            tag = val["tag"]
            expected = str(val["expected_value"]).strip().lower()
            tag_match = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", content, re.IGNORECASE)
            extracted = tag_match.group(1).strip().lower() if tag_match else None

            if extracted is None:
                # Fallback: check if the expected answer appears in content or reasoning
                passed = expected in content or expected in reasoning
                score = 0.7 if passed else 0.0
            else:
                passed = (extracted == expected)
                if not passed and "tolerance" in val:
                    try:
                        passed = abs(float(extracted) - float(expected)) <= val["tolerance"]
                    except Exception:
                        pass
                score = 1.0 if passed else 0.0

            return {
                "task_id": task["task_id"],
                "passed": passed,
                "score": score,
                "latency_ms": round(latency_ms, 2),
                "extracted": extracted,
                "expected": expected
            }

        elif vtype == "constrained_text":
            bullet_prefix = val.get("bullet_prefix", "* ")
            expected_count = val.get("bullet_count", 3)
            min_w = val.get("min_words_per_bullet", 5)
            max_w = val.get("max_words_per_bullet", 9)
            forbidden = val.get("forbidden_words", [])

            lines = [line.strip() for line in content.splitlines() if line.strip().startswith(bullet_prefix) or line.strip().startswith("- ")]
            count_ok = len(lines) == expected_count

            # Word bounds check
            words_ok = True
            for l in lines:
                text_clean = l.lstrip("*-• ").strip()
                word_count = len(text_clean.split())
                if word_count < min_w or word_count > max_w:
                    words_ok = False

            # Forbidden words check
            forbidden_ok = not any(w.lower() in content.lower() for w in forbidden)

            passed = count_ok and words_ok and forbidden_ok
            score = (0.4 if count_ok else 0) + (0.3 if words_ok else 0) + (0.3 if forbidden_ok else 0)

            return {
                "task_id": task["task_id"],
                "passed": passed,
                "score": round(score, 2),
                "latency_ms": round(latency_ms, 2),
                "bullet_count": len(lines),
                "forbidden_absent": forbidden_ok
            }

        return {"task_id": task["task_id"], "passed": False, "score": 0.0, "latency_ms": round(latency_ms, 2)}
    except Exception as e:
        return {"task_id": task["task_id"], "passed": False, "score": 0.0, "latency_ms": 0.0, "error": str(e)}


def evaluate_vision(gateway_url: str, model: str, task: dict) -> Dict[str, Any]:
    """Execute vision understanding with base64 image inspection."""
    chat_url = f"{gateway_url.rstrip('/')}/v1/chat/completions"
    img_b64 = task["image_b64"]
    media_type = task.get("media_type", "image/png")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": task["prompt"]},
                    {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{img_b64}"}}
                ]
            }
        ],
        "max_tokens": 300
    }

    try:
        status, body, latency_ms = post_gateway(chat_url, payload)
        content = body["choices"][0]["message"].get("content") or ""
        reasoning = body["choices"][0]["message"].get("reasoning") or ""

        # Extract JSON from output
        json_match = re.search(r"\{.*?\}", content, re.DOTALL)
        parsed = None
        if json_match:
            try:
                parsed = json.loads(json_match.group(0))
            except Exception:
                pass

        val = task["validation"]
        fields = val.get("fields", {})
        matched_fields = 0
        total_fields = len(fields)

        for k, v in fields.items():
            if parsed and k in parsed:
                actual = parsed[k]
                if isinstance(v, list):
                    if any(str(opt).lower() in str(actual).lower() for opt in v):
                        matched_fields += 1
                elif str(actual).lower() == str(v).lower():
                    matched_fields += 1
            else:
                # Text fallback check in content or reasoning
                if isinstance(v, list):
                    if any(str(opt).lower() in content.lower() or str(opt).lower() in reasoning.lower() for opt in v):
                        matched_fields += 1
                elif str(v).lower() in content.lower() or str(v).lower() in reasoning.lower():
                    matched_fields += 1

        score = matched_fields / total_fields if total_fields > 0 else 1.0
        passed = score >= 0.5

        return {
            "task_id": task["task_id"],
            "passed": passed,
            "score": round(score, 2),
            "latency_ms": round(latency_ms, 2),
            "extracted": parsed or content[:100]
        }
    except Exception as e:
        return {"task_id": task["task_id"], "passed": False, "score": 0.0, "latency_ms": 0.0, "error": str(e)}


def evaluate_language(gateway_url: str, model: str, task: dict) -> Dict[str, Any]:
    """Execute language quality evaluation (Arabic syntax/nuance and English technical clarity)."""
    chat_url = f"{gateway_url.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": task["prompt"]}],
        "max_tokens": 400
    }

    try:
        status, body, latency_ms = post_gateway(chat_url, payload)
        content = body["choices"][0]["message"].get("content") or ""

        val = task["validation"]
        vtype = val.get("type")

        if vtype == "keyword_semantic":
            groups = val.get("required_any_groups", [])
            matched_groups = 0
            for grp in groups:
                if any(term in content for term in grp):
                    matched_groups += 1

            score = matched_groups / len(groups) if groups else 1.0
            passed = score >= 0.66

            return {
                "task_id": task["task_id"],
                "passed": passed,
                "score": round(score, 2),
                "latency_ms": round(latency_ms, 2),
                "matched_groups": f"{matched_groups}/{len(groups)}"
            }

        elif vtype == "technical_density":
            max_words = val.get("max_words", 130)
            required_concepts = val.get("required_concepts", [])

            words = content.split()
            word_count = len(words)
            length_ok = word_count <= (max_words + 15)  # slight tolerance

            matched_concepts = [c for c in required_concepts if c.lower() in content.lower()]
            concepts_ok = len(matched_concepts) >= (len(required_concepts) * 0.75)

            score = (0.5 if length_ok else 0.2) + (0.5 * (len(matched_concepts) / len(required_concepts)))
            passed = length_ok and concepts_ok

            return {
                "task_id": task["task_id"],
                "passed": passed,
                "score": round(score, 2),
                "latency_ms": round(latency_ms, 2),
                "word_count": word_count,
                "matched_concepts": matched_concepts
            }

        return {"task_id": task["task_id"], "passed": False, "score": 0.0, "latency_ms": round(latency_ms, 2)}
    except Exception as e:
        return {"task_id": task["task_id"], "passed": False, "score": 0.0, "latency_ms": 0.0, "error": str(e)}


def run_benchmark(gateway_url: str = "http://127.0.0.1:8080", target_models: Optional[List[str]] = None) -> Tuple[dict, dict]:
    """Execute complete empirical probe evaluation across active routes and save datasets."""
    gw_proc = ensure_gateway(gateway_url)

    try:
        with open(TASKS_PATH, "r", encoding="utf-8") as f:
            task_data = json.load(f)

        tasks = task_data["tasks"]

        # Discover active models
        models_to_test = target_models or []
        if not models_to_test:
            try:
                req = urllib.request.Request(f"{gateway_url.rstrip('/')}/v1/models")
                with urllib.request.urlopen(req, timeout=10) as r:
                    mdata = json.loads(r.read().decode("utf-8"))
                    models_to_test = [m["id"] for m in mdata.get("data", []) if m.get("id") and m.get("id") != "*"]
            except Exception:
                models_to_test = ["openai/gpt-oss-20b", "qwen/qwen3-30b-a3b", "google/gemma-3-12b-it", "ministral-8b-latest"]

        # Deduplicate and prioritize active working candidates
        active_candidates = []
        for m in models_to_test:
            if m not in active_candidates:
                active_candidates.append(m)

        # Select primary representative models for the real probe sweep
        primary_routes = active_candidates[:4] if len(active_candidates) > 4 else active_candidates

        all_results = []
        leaderboard_entries = []
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

        print(f"=== Starting Empirical Evaluation on {len(primary_routes)} Routes ===")

        for model in primary_routes:
            print(f"\n--- Testing Route / Model: {model} ---")
            # 1. Measure empirical TTFT and Generation Throughput
            perf = measure_ttft_and_throughput(gateway_url, model)
            print(f"  Streaming TTFT: {perf['ttft_ms']} ms | Throughput: {perf['throughput_tok_s']} tokens/sec")

            # 2. Execute Tasks Suite
            task_results = []
            category_stats = {}

            for task in tasks:
                cat = task["category"]
                if cat not in category_stats:
                    category_stats[cat] = {"total": 0, "passed": 0, "scores": []}

                category_stats[cat]["total"] += 1

                if cat == "tool_call_validity":
                    res = evaluate_tool_call_validity(gateway_url, model, task)
                elif cat == "multi_step_tool_loop":
                    res = evaluate_multi_step_loop(gateway_url, model, task)
                elif cat == "code_edit_correctness":
                    res = evaluate_code_edit(gateway_url, model, task)
                elif cat == "instruction_following_reasoning":
                    res = evaluate_reasoning(gateway_url, model, task)
                elif cat == "vision_understanding":
                    res = evaluate_vision(gateway_url, model, task)
                elif cat == "language_quality":
                    res = evaluate_language(gateway_url, model, task)
                else:
                    res = {"task_id": task["task_id"], "passed": False, "score": 0.0, "latency_ms": 0.0}

                res["category"] = cat
                res["model"] = model
                res["timestamp"] = timestamp
                task_results.append(res)
                all_results.append(res)

                if res["passed"]:
                    category_stats[cat]["passed"] += 1
                category_stats[cat]["scores"].append(res["score"])

                status_str = "PASS" if res["passed"] else "FAIL"
                print(f"  [{status_str}] {task['task_id']} ({cat}) score={res['score']} latency={res.get('latency_ms', 0)}ms")

            # Compute aggregates for this route
            total_tasks = len(task_results)
            passed_tasks = sum(1 for r in task_results if r["passed"])
            overall_success_rate = round(passed_tasks / total_tasks, 4) if total_tasks > 0 else 0.0
            ci_lower, ci_upper = wilson_score_interval(passed_tasks, total_tasks, 0.95)

            avg_latency = round(sum(r.get("latency_ms", 0.0) for r in task_results) / total_tasks, 2) if total_tasks > 0 else 0.0

            cat_breakdown = {}
            for cat, cs in category_stats.items():
                c_tot = cs["total"]
                c_pass = cs["passed"]
                c_rate = round(c_pass / c_tot, 4) if c_tot > 0 else 0.0
                c_low, c_high = wilson_score_interval(c_pass, c_tot, 0.95)
                cat_breakdown[cat] = {
                    "sample_size_N": c_tot,
                    "passed": c_pass,
                    "success_rate": c_rate,
                    "ci_95": [c_low, c_high],
                    "avg_score": round(sum(cs["scores"]) / c_tot, 4) if c_tot > 0 else 0.0
                }

            entry = {
                "model": model,
                "sample_size_N": total_tasks,
                "success_rate": overall_success_rate,
                "ci_95": [ci_lower, ci_upper],
                "ttft_ms": perf["ttft_ms"],
                "throughput_tok_s": perf["throughput_tok_s"],
                "avg_task_latency_ms": avg_latency,
                "category_breakdown": cat_breakdown,
                "timestamp": timestamp
            }
            leaderboard_entries.append(entry)

        # Sort leaderboard by success rate descending, then throughput descending
        leaderboard_entries.sort(key=lambda x: (x["success_rate"], x["throughput_tok_s"]), reverse=True)

        results_data = {
            "version": "1.0.0",
            "benchmark_timestamp": timestamp,
            "gateway_url": gateway_url,
            "total_probes": len(all_results),
            "results": all_results
        }

        leaderboard_data = {
            "version": "1.0.0",
            "benchmark_timestamp": timestamp,
            "total_models": len(leaderboard_entries),
            "models": leaderboard_entries
        }

        # Save to disk
        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(results_data, f, indent=2, ensure_ascii=False)

        with open(LEADERBOARD_PATH, "w", encoding="utf-8") as f:
            json.dump(leaderboard_data, f, indent=2, ensure_ascii=False)

        print(f"\nSaved {len(all_results)} detailed task executions to {RESULTS_PATH}")
        print(f"Saved {len(leaderboard_entries)} leaderboard rankings to {LEADERBOARD_PATH}")

        return results_data, leaderboard_data
    finally:
        if gw_proc:
            try:
                gw_proc.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    run_benchmark()
