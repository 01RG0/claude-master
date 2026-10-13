"""Offline summary of real CLI task-run manifests (no provider calls).

Cost is reported strictly as CLI-reported cost. It is not a provider invoice or
gateway spend measurement. Missing cost/usage fields remain NOT MEASURED.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path


def _binom_tail(n: int, p: float, k: int, upper: bool) -> float:
    """P[X >= k] if upper else P[X <= k], evaluated stably for modest n."""
    if p <= 0:
        return 1.0 if (k <= 0 if upper else k >= 0) else 0.0
    if p >= 1:
        return 1.0 if (k <= n if upper else k >= n) else 0.0
    lo, hi = (k, n) if upper else (0, k)
    if lo > hi:
        return 0.0
    logs = [math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
            + i * math.log(p) + (n - i) * math.log1p(-p) for i in range(lo, hi + 1)]
    peak = max(logs)
    return min(1.0, math.exp(peak) * sum(math.exp(x - peak) for x in logs))


def exact_binomial_ci(successes: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Two-sided Clopper-Pearson interval, by inversion of exact binomial tails."""
    if not 0 <= successes <= n or n <= 0:
        raise ValueError("require 0 <= successes <= n and n > 0")
    tail = alpha / 2
    if successes == 0:
        lower = 0.0
    else:
        left, right = 0.0, successes / n
        for _ in range(70):
            mid = (left + right) / 2
            # P_p[X >= successes] increases with p; lower endpoint equals tail.
            if _binom_tail(n, mid, successes, True) < tail:
                left = mid
            else:
                right = mid
        lower = (left + right) / 2
    if successes == n:
        upper = 1.0
    else:
        left, right = successes / n, 1.0
        for _ in range(70):
            mid = (left + right) / 2
            # P_p[X <= successes] decreases with p; upper endpoint equals tail.
            if _binom_tail(n, mid, successes, False) > tail:
                left = mid
            else:
                right = mid
        upper = (left + right) / 2
    return lower, upper


def exact_sign_test(a_wins: int, b_wins: int) -> float | None:
    """Two-sided exact sign-test p-value over non-tied paired task outcomes."""
    n = a_wins + b_wins
    if n == 0:
        return None
    tail = sum(math.comb(n, i) for i in range(min(a_wins, b_wins) + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    vals = sorted(values)
    pos = (len(vals) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def _fmt(value: float | None, digits: int = 3) -> str:
    return "NOT MEASURED" if value is None else f"{value:.{digits}f}"


def load_manifest(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc.get("results"), list):
        raise ValueError(f"{path}: missing results list")
    return doc


def _usage_tokens(record: dict) -> tuple[int | None, int | None]:
    usage = record.get("usage")
    if not isinstance(usage, dict):
        return None, None
    inp = usage.get("input_tokens", usage.get("prompt_tokens"))
    out = usage.get("output_tokens", usage.get("completion_tokens"))
    return (int(inp) if isinstance(inp, (int, float)) else None,
            int(out) if isinstance(out, (int, float)) else None)


def summarize(manifest: dict) -> dict:
    measured = [r for r in manifest["results"] if r.get("status") == "MEASURED" and isinstance(r.get("success"), bool)]
    successes = sum(r["success"] for r in measured)
    n = len(measured)
    ci = exact_binomial_ci(successes, n) if n else None
    lat = [float(r["wall_seconds"]) for r in measured if isinstance(r.get("wall_seconds"), (int, float))]
    turns = [int(r["turns"]) for r in measured if isinstance(r.get("turns"), (int, float))]
    in_tokens, out_tokens = [], []
    for r in measured:
        it, ot = _usage_tokens(r)
        if it is not None:
            in_tokens.append(it)
        if ot is not None:
            out_tokens.append(ot)
    costs = [float(r["total_cost_usd"]) for r in measured if isinstance(r.get("total_cost_usd"), (int, float))]
    complete_cost = len(costs) == n and n > 0
    cost_per_success = (sum(costs) / successes) if complete_cost and successes else None
    success_per_cli_dollar = (successes / sum(costs)) if complete_cost and sum(costs) > 0 else None
    duration_complete = len(lat) == n and n > 0
    success_per_second = successes / sum(lat) if duration_complete and sum(lat) > 0 else None
    return {"model": manifest.get("model", "UNKNOWN"), "run_id": manifest.get("run_id", "UNKNOWN"),
            "measured_n": n, "not_measured_n": len(manifest["results"]) - n, "successes": successes,
            "success_rate": successes / n if n else None, "ci": ci,
            "p50_seconds": _quantile(lat, .50) if len(lat) == n and n else None,
            "p95_seconds": _quantile(lat, .95) if len(lat) == n and n else None,
            "turns_mean": statistics.mean(turns) if len(turns) == n and n else None,
            "input_tokens_mean": statistics.mean(in_tokens) if len(in_tokens) == n and n else None,
            "output_tokens_mean": statistics.mean(out_tokens) if len(out_tokens) == n and n else None,
            "success_per_cli_dollar": success_per_cli_dollar,
            "cost_per_success_cli_usd": cost_per_success,
            "success_per_second": success_per_second,
            "cost_complete": complete_cost, "latency_n": len(lat), "turns_n": len(turns),
            "input_tokens_n": len(in_tokens), "output_tokens_n": len(out_tokens)}


def compare(a: dict, b: dict) -> dict:
    def by_task(man):
        grouped: dict[str, dict[int, bool]] = {}
        for r in man["results"]:
            if r.get("status") == "MEASURED" and isinstance(r.get("success"), bool):
                grouped.setdefault(r.get("task_id"), {})[r.get("repetition")] = r["success"]
        return grouped
    aa, bb = by_task(a), by_task(b)
    common_tasks = sorted(aa.keys() & bb.keys())
    a_wins = b_wins = ties = paired_tasks = 0
    paired_repetitions = 0
    for task_id in common_tasks:
        reps = aa[task_id].keys() & bb[task_id].keys()
        if not reps:
            continue
        paired_tasks += 1
        paired_repetitions += len(reps)
        # Repetitions estimate each task's success fraction; the sign test's
        # independent unit remains the task, not task x repetition.
        a_rate = sum(aa[task_id][r] for r in reps) / len(reps)
        b_rate = sum(bb[task_id][r] for r in reps) / len(reps)
        if a_rate > b_rate:
            a_wins += 1
        elif b_rate > a_rate:
            b_wins += 1
        else:
            ties += 1
    return {"paired_tasks": paired_tasks, "paired_repetitions": paired_repetitions,
            "non_tied_tasks_tested": a_wins + b_wins, "tied_tasks": ties,
            "a_better_tasks": a_wins, "b_better_tasks": b_wins,
            "exact_sign_test_p": exact_sign_test(a_wins, b_wins),
            "tasks_unpaired_or_missing_in_a": len(bb.keys() - aa.keys()),
            "tasks_unpaired_or_missing_in_b": len(aa.keys() - bb.keys())}


def to_markdown(summaries: list[dict], comparisons: list[tuple[str, str, dict]]) -> str:
    lines = ["| System / run | Successes/N | Success rate (exact 95% CI) | E2E p50/p95 (s) | Mean turns | Mean input/output tokens | Success / CLI-reported USD | Success / second |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for s in summaries:
        ci = s["ci"]
        rate = (f"{s['success_rate']:.3f} ({ci[0]:.3f}–{ci[1]:.3f})" if ci else "NOT MEASURED")
        lines.append(f"| {s['model']} / {s['run_id']} | {s['successes']}/{s['measured_n']} | {rate} | "
                     f"{_fmt(s['p50_seconds'])}/{_fmt(s['p95_seconds'])} | {_fmt(s['turns_mean'])} | "
                     f"{_fmt(s['input_tokens_mean'], 1)}/{_fmt(s['output_tokens_mean'], 1)} | "
                     f"{_fmt(s['success_per_cli_dollar'])} | {_fmt(s['success_per_second'])} |")
    lines.extend(["", "CLI-reported USD is not a provider invoice or gateway spend. Provider success/$: NOT MEASURED.",
                  "Latency quantiles use linear interpolation over measured end-to-end wall times. Token/turn summaries require complete fields for all measured rows.",
                  ""])
    if comparisons:
        lines += ["Paired two-sided exact sign tests (task is the unit; repetition outcomes are averaged within each task; ties excluded):", "",
                  "| A | B | Paired tasks | Paired reps | Non-tied tasks | Tied tasks | A-better tasks | B-better tasks | Exact sign-test p |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
        for an, bn, c in comparisons:
            lines.append(f"| {an} | {bn} | {c['paired_tasks']} | {c['paired_repetitions']} | {c['non_tied_tasks_tested']} | {c['tied_tasks']} | {c['a_better_tasks']} | {c['b_better_tasks']} | {_fmt(c['exact_sign_test_p'])} |")
    return "\n".join(lines) + "\n"


def self_test() -> None:
    # Synthetic fixtures validate math only; never print their values as results.
    lo, hi = exact_binomial_ci(5, 10)
    assert abs(lo - 0.187086) < 1e-5 and abs(hi - 0.812914) < 1e-5
    assert exact_binomial_ci(0, 10)[0] == 0 and exact_binomial_ci(10, 10)[1] == 1
    assert abs(exact_sign_test(5, 0) - 0.0625) < 1e-12
    a = {"model": "A", "run_id": "a", "results": [
        {"task_id": "x", "repetition": 1, "status": "MEASURED", "success": True},
        {"task_id": "y", "repetition": 1, "status": "MEASURED", "success": False}]}
    b = {"model": "B", "run_id": "b", "results": [
        {"task_id": "x", "repetition": 1, "status": "MEASURED", "success": False},
        {"task_id": "y", "repetition": 1, "status": "MEASURED", "success": True}]}
    paired = compare(a, b)
    assert paired["paired_tasks"] == 2 and paired["paired_repetitions"] == 2
    assert paired["exact_sign_test_p"] == 1.0
    # Five repetitions per task still yield only two independent task units.
    rep_a = {"results": [{"task_id": t, "repetition": r, "status": "MEASURED", "success": r <= 4}
                          for t in ("x", "y") for r in range(1, 6)]}
    rep_b = {"results": [{"task_id": t, "repetition": r, "status": "MEASURED", "success": r == 5}
                          for t in ("x", "y") for r in range(1, 6)]}
    clustered = compare(rep_a, rep_b)
    assert clustered["paired_tasks"] == 2 and clustered["paired_repetitions"] == 10
    assert clustered["non_tied_tasks_tested"] == 2 and clustered["exact_sign_test_p"] == 0.5
    s = summarize({"model": "S", "run_id": "s", "results": [
        {"status": "MEASURED", "success": True, "wall_seconds": 2, "total_cost_usd": None},
        {"status": "NOT MEASURED"}]})
    assert s["success_per_cli_dollar"] is None and s["success_per_second"] == 0.5


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("manifests", nargs="*", type=Path)
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"), type=Path, action="append", default=[])
    ap.add_argument("--output", type=Path)
    ap.add_argument("--self-test", action="store_true", help="run synthetic math/handling assertions; prints no fixture values")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        print("synthetic self-test: PASS")
        return 0
    paths = list(dict.fromkeys(args.manifests + [p for pair in args.compare for p in pair]))
    if not paths:
        ap.error("provide one or more manifest paths, or --self-test")
    docs = {p: load_manifest(p) for p in paths}
    summaries = [summarize(docs[p]) for p in paths]
    comparisons = [(str(a), str(b), compare(docs[a], docs[b])) for a, b in args.compare]
    output = to_markdown(summaries, comparisons)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
