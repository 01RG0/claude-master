"""Drex latency benchmark: 220 sequential live calls (rewrite).

Measures round-trip p50/p95/p99 + server evaluation_time_ms distribution,
tokens and cost. Markdown decision log is redirected to tempdir so the repo
stays clean; JSONL still goes to the default log dir (outside repo).
Prints one line per 20 calls (redacted: no states, no keys).
"""
import os
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from brain.judge.client import DrexClient  # noqa: E402

N = 220
STATE = "Benchmark probe: routine developer workspace listing files."
QUESTIONS = {"is_routine": {"type": "noul", "instructions": "Is this a routine safe developer action?"}}


def pct(xs, q):
    s = sorted(xs)
    return s[min(len(s) - 1, int(len(s) * q / 100))]


def main():
    c = DrexClient(timeout_s=60, max_retries=2)
    c._repo_root = Path(tempfile.gettempdir()) / "drex-bench"
    print(f"model (resolved): {c.resolve_model()}", flush=True)
    rts, evals, fails = [], [], 0
    for i in range(N):
        t0 = time.perf_counter()
        r = c.evaluate(f"{STATE} probe {i} of {N} id-{i * 7919}", QUESTIONS)
        dt = (time.perf_counter() - t0) * 1000
        if r.get("_fail_open"):
            fails += 1
            continue
        rts.append(dt)
        try:
            evals.append(float(r.get("evaluation_time_ms", 0) or 0))
        except (TypeError, ValueError):
            pass
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{N} ...", flush=True)
    print(f"roundtrip_ms (n={len(rts)}, fail_open={fails}): "
          f"min={min(rts):.0f} p50={pct(rts,50):.0f} p95={pct(rts,95):.0f} p99={pct(rts,99):.0f} max={max(rts):.0f}")
    if evals:
        print(f"server evaluation_time_ms: min={min(evals):.0f} p50={pct(evals,50):.0f} "
              f"p95={pct(evals,95):.0f} p99={pct(evals,99):.0f} max={max(evals):.0f}")
    print(f"cost: {c.cost_summary()}")


if __name__ == "__main__":
    main()
