"""power_calculation.py — Statistical Power & Sample Size Calculator for Model Evaluation.

Computes required sample size N to detect claimed effect sizes (Delta = 0.10 to 0.25)
between model architectures and prompt strategies at alpha = 0.05 and power (1 - beta) = 0.80 / 0.90.

Supports:
1. Two-sample independent proportions test (Z-test / pooled variance).
2. Paired proportions test (McNemar's test for benchmark task suites where models are evaluated on the identical task set).
3. Exports formal power tables to data/evals/power_analysis.json.
"""

from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_PATH = os.path.join(REPO_ROOT, "data", "evals", "power_analysis.json")


def z_value(p: float) -> float:
    """Standard normal quantile function approximation (Acklam's algorithm)."""
    # Rational approximation for central and tail regions
    if p <= 0.0 or p >= 1.0:
        raise ValueError("p must be in (0, 1)")

    # Coefficients for approximation
    a = [-3.969683028665376e+01, 2.209460984245205e+02,
         -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02,
         -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01,
         2.445134137142996e+00, 3.754408661907416e+00]

    q = min(p, 1.0 - p)
    if q > 0.02425:
        r = q - 0.5
        r2 = r * r
        num = (((((a[0]*r2 + a[1])*r2 + a[2])*r2 + a[3])*r2 + a[4])*r2 + a[5]) * r
        den = (((((b[0]*r2 + b[1])*r2 + b[2])*r2 + b[3])*r2 + b[4])*r2 + 1.0)
        z = num / den
    else:
        r = math.sqrt(-math.log(q))
        num = (((((c[0]*r + c[1])*r + c[2])*r + c[3])*r + c[4])*r + c[5])
        den = ((((d[0]*r + d[1])*r + d[2])*r + d[3])*r + 1.0)
        z = num / den
        if p < 0.5:
            z = -z
    return z if p >= 0.5 else -abs(z)


def sample_size_two_proportions(
    p1: float,
    p2: float,
    alpha: float = 0.05,
    power: float = 0.80
) -> int:
    """Calculate required sample size N per group for two independent proportions."""
    delta = abs(p1 - p2)
    if delta < 1e-5:
        raise ValueError("p1 and p2 must be distinct")

    z_alpha = abs(z_value(1.0 - alpha / 2.0))
    z_beta = abs(z_value(power))

    p_bar = (p1 + p2) / 2.0
    term1 = z_alpha * math.sqrt(2.0 * p_bar * (1.0 - p_bar))
    term2 = z_beta * math.sqrt(p1 * (1.0 - p1) + p2 * (1.0 - p2))

    n = ((term1 + term2) ** 2) / (delta ** 2)
    return int(math.ceil(n))


def sample_size_paired_mcnemar(
    p1: float,
    p2: float,
    discordant_ratio: float = 0.30,
    alpha: float = 0.05,
    power: float = 0.80
) -> int:
    """Calculate required sample size N for paired testing (McNemar's test).

    On benchmark suites, both models evaluate the exact same tasks.
    discordant_ratio (p_01 + p_10) typically ranges between 0.20 and 0.40.
    """
    delta = abs(p1 - p2)
    if delta < 1e-5:
        raise ValueError("p1 and p2 must be distinct")

    z_alpha = abs(z_value(1.0 - alpha / 2.0))
    z_beta = abs(z_value(power))

    p_disc = max(discordant_ratio, delta + 0.05)
    term1 = z_alpha * math.sqrt(p_disc)
    term2 = z_beta * math.sqrt(p_disc - delta ** 2)

    n = ((term1 + term2) ** 2) / (delta ** 2)
    return int(math.ceil(n))


def generate_power_matrix() -> Dict[str, Any]:
    """Generate comprehensive power calculation matrix across effect sizes and baseline success rates."""
    deltas = [0.10, 0.15, 0.20, 0.25]
    baselines = [0.50, 0.60, 0.70]
    powers = [0.80, 0.90]
    alpha = 0.05

    results_table = []
    for base in baselines:
        for delta in deltas:
            p2 = min(0.99, base + delta)
            for pwr in powers:
                n_indep = sample_size_two_proportions(base, p2, alpha=alpha, power=pwr)
                n_paired = sample_size_paired_mcnemar(base, p2, discordant_ratio=0.30, alpha=alpha, power=pwr)
                results_table.append({
                    "baseline_p1": base,
                    "target_p2": round(p2, 2),
                    "effect_size_delta": delta,
                    "alpha": alpha,
                    "target_power": pwr,
                    "required_N_independent": n_indep,
                    "required_N_paired_benchmark": n_paired
                })

    paired_effect_targets = {
        "baseline_rate": 0.50,
        "discordant_pair_fraction": 0.30,
        "alpha": alpha,
        "target_power": 0.80,
        "required_tasks_per_category": {
            "absolute_difference_0_20": sample_size_paired_mcnemar(
                0.50, 0.70, discordant_ratio=0.30, alpha=alpha, power=0.80
            ),
            "absolute_difference_0_15": sample_size_paired_mcnemar(
                0.50, 0.65, discordant_ratio=0.30, alpha=alpha, power=0.80
            ),
        },
        "method": "Normal approximation to paired McNemar test with stated discordance assumption",
        "interpretation": "Planning calculation only; assumptions must be checked against pilot discordant pairs.",
    }

    report = {
        "title": "Empirical Model Evaluation Statistical Power Analysis",
        "description": "Paired sample-size calculations. These are design assumptions, not benchmark results.",
        "recommended_task_suite_size": {
            "minimum_total_tasks": 180,
            "tasks_per_category": 30,
            "categories_count": 6,
            "status": "minimum floor only; not sufficient for the effect targets below",
        },
        "paired_effect_targets": paired_effect_targets,
        "power_matrix": results_table
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return report


if __name__ == "__main__":
    rep = generate_power_matrix()
    print("=== Statistical Power & Sample Size Report Generated ===")
    rec = rep["recommended_task_suite_size"]
    print(f"Total Tasks Recommended: {rec['minimum_total_tasks']} ({rec['tasks_per_category']} per category across {rec['categories_count']} categories)")
    print(f"Minimum floor: {rec['minimum_total_tasks']} ({rec['tasks_per_category']} per category)")
    paired = rep["paired_effect_targets"]["required_tasks_per_category"]
    print(f"Paired N for 0.20 difference at 80% power: {paired['absolute_difference_0_20']}")
    print(f"Paired N for 0.15 difference at 80% power: {paired['absolute_difference_0_15']}")
    print(f"Saved to: {OUTPUT_PATH}")
