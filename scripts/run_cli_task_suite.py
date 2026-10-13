"""Run the CLI-compatible portion of data/evals/tasks.json.

Every invocation gets an isolated artifact directory and every task repetition
gets a fresh working directory. This runner deliberately does not emulate tools
that are not exposed by Claude Code's built-in CLI tool interface.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK_FILE = ROOT / "data" / "evals" / "tasks.json"
SUPPORTED = {"instruction_following_reasoning", "code_edit_correctness", "language_quality"}
UNSUPPORTED = {
    "tool_call_validity": "NOT MEASURED: task JSON function schemas cannot be registered as native Claude Code CLI tools by this runner.",
    "multi_step_tool_loop": "NOT MEASURED: requires executable mock tool implementations and tool-call trace capture; task JSON alone does not provide a CLI tool server.",
    "vision_understanding": "NOT MEASURED: image_b64 is not passed as a native Claude Code CLI image attachment by this runner.",
}


def oracle(task: dict, answer: str, work: Path) -> tuple[bool | None, str]:
    category = task["category"]
    if category == "instruction_following_reasoning":
        v = task.get("validation") or {}
        tag = re.escape(v.get("tag", "answer"))
        m = re.search(rf"<{tag}>(.*?)</{tag}>", answer, re.I | re.S)
        ok = bool(m and m.group(1).strip() == str(v.get("expected_value", "")))
        return ok, "exact_tag" if m else "missing_exact_tag"
    if category == "language_quality":
        groups = (task.get("validation") or {}).get("required_any_groups", [])
        # Dataset groups contain alternative literal terms, sometimes mojibake;
        # use the saved strings exactly and disclose this deterministic oracle.
        failed = [group for group in groups if not any(term.lower() in answer.lower() for term in group)]
        return not failed, "keyword_groups" if not failed else "missing_groups:" + json.dumps(failed, ensure_ascii=False)
    if category == "code_edit_correctness":
        symbol = task.get("target_symbol")
        m = re.search(r"```(?:python)?\s*(.*?)```", answer, re.I | re.S)
        code = m.group(1) if m else answer.strip()
        if not symbol or not re.search(rf"\bdef\s+{re.escape(symbol)}\s*\(", code):
            return False, "missing_target_function"
        suite = task.get("test_suite") or ""
        harness = work / "oracle.py"
        harness.write_text(code + "\n\n" + suite + f"\nassert run_tests({symbol}) is True\n", encoding="utf-8")
        try:
            p = subprocess.run([sys.executable, str(harness)], cwd=work, capture_output=True, text=True, timeout=10)
            return p.returncode == 0, "passed_project_suite" if p.returncode == 0 else "project_suite_failed:" + (p.stderr[-1000:] or p.stdout[-1000:])
        except subprocess.TimeoutExpired:
            return False, "project_suite_timeout"
    return None, "NOT MEASURED"


def cli_call(prompt: str, model: str, cwd: Path, timeout: int, max_budget: float | None) -> dict:
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", model,
           "--permission-mode", "dontAsk", "--permission-prompts", "none",
           "--no-session-persistence", "--bare", "--tools", ""]
    if max_budget is not None:
        cmd.extend(["--max-budget-usd", str(max_budget)])
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        wall = time.perf_counter() - t0
        raw = p.stdout
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {}
        return {"returncode": p.returncode, "stdout": raw, "stderr": p.stderr,
                "wall_seconds": wall, "parsed": parsed,
                "answer": parsed.get("result", raw),
                "session_id": parsed.get("session_id"), "num_turns": parsed.get("num_turns"),
                "usage": parsed.get("usage"), "total_cost_usd": parsed.get("total_cost_usd")}
    except subprocess.TimeoutExpired as e:
        return {"returncode": None, "stdout": e.stdout or "", "stderr": e.stderr or "",
                "wall_seconds": time.perf_counter() - t0, "parsed": {}, "answer": "",
                "session_id": None, "num_turns": None, "usage": None,
                "total_cost_usd": None, "timeout": True}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="Claude CLI --model value")
    ap.add_argument("--repetitions", type=int, default=1)
    ap.add_argument("--seed", type=int, default=1, help="Recorded seed; CLI/API does not expose a controllable seed")
    ap.add_argument("--category", action="append", choices=sorted(SUPPORTED | set(UNSUPPORTED)))
    ap.add_argument("--task-id", action="append")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--max-budget-usd", type=float)
    ap.add_argument("--output-root", type=Path, default=ROOT / "data" / "evals" / "cli_runs")
    args = ap.parse_args()
    if args.repetitions < 1:
        ap.error("--repetitions must be >= 1")
    tasks_doc = json.loads(TASK_FILE.read_text(encoding="utf-8"))
    selected = [t for t in tasks_doc["tasks"] if (not args.category or t["category"] in args.category)
                and (not args.task_id or t["task_id"] in args.task_id)]
    run_id = str(uuid.uuid4())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    outdir = args.output_root / f"{stamp}_{run_id}"
    outdir.mkdir(parents=True, exist_ok=False)
    records = []
    for task in selected:
        for rep in range(args.repetitions):
            seed = args.seed + rep
            record = {"run_id": run_id, "task_id": task["task_id"], "category": task["category"],
                      "model": args.model, "repetition": rep + 1, "seed": seed,
                      "seed_applied": False, "task_sha256": hashlib.sha256(json.dumps(task, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                      "artifact_path": None, "status": "NOT MEASURED"}
            if task["category"] not in SUPPORTED:
                record["reason"] = UNSUPPORTED[task["category"]]
            else:
                work = outdir / "work" / task["task_id"] / f"rep_{rep + 1}"
                work.mkdir(parents=True, exist_ok=False)
                result = cli_call(task["prompt"], args.model, work, args.timeout, args.max_budget_usd)
                passed, oracle_detail = oracle(task, str(result["answer"]), work)
                record.update({"status": "MEASURED", "success": bool(passed), "oracle": oracle_detail,
                               "wall_seconds": result["wall_seconds"], "turns": result["num_turns"],
                               "usage": result["usage"], "total_cost_usd": result["total_cost_usd"],
                               "session_id": result["session_id"], "returncode": result["returncode"],
                               "timeout": result.get("timeout", False), "stdout": result["stdout"],
                               "stderr": result["stderr"]})
            artifact = outdir / f"{task['task_id']}_rep{rep + 1}.json"
            artifact.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
            record["artifact_path"] = str(artifact.resolve())
            # Rewrite after artifact path becomes known, so the artifact is self-describing.
            artifact.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
            records.append(record)
            print(json.dumps({k: record.get(k) for k in ("run_id", "task_id", "category", "repetition", "status", "success", "artifact_path")}, ensure_ascii=False), flush=True)
    manifest = {"run_id": run_id, "created_utc": datetime.now(timezone.utc).isoformat(), "model": args.model,
                "repetitions": args.repetitions, "seed_base": args.seed, "seed_controlled_by_cli": False,
                "task_file": str(TASK_FILE), "task_file_sha256": hashlib.sha256(TASK_FILE.read_bytes()).hexdigest(),
                "selected_task_count": len(selected), "results": records,
                "unsupported_categories": {c: UNSUPPORTED[c] for c in set(t["category"] for t in selected) if c in UNSUPPORTED}}
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"MANIFEST={outdir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
