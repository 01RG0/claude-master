"""paired_significance.py — Paired Significance Testing for Model Benchmark Comparison.

Implements:
1. McNemar's Test with Edward's continuity correction for paired binary outcomes.
2. Exact Binomial Test for small discordant counts (b + c < 25).
3. Paired Permutation Test (Monte Carlo / exact) for empirical distribution.
4. Formal flagging: "Difference not statistically significant" when p >= 0.05.
"""

from __future__ import annotations

import json
import math
import random
import sys
from typing import Any, Dict, List, Optional, Tuple


def normal_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def exact_binomial_two_tailed(k: int, n: int, p: float = 0.5) -> float:
    """Exact two-tailed binomial test for discordant pairs in McNemar's test."""
    if n == 0:
        return 1.0

    k_min = min(k, n - k)
    # Cumulative probability sum
    p_val = 0.0
    for i in range(k_min + 1):
        comb = math.comb(n, i)
        p_val += comb * (p ** n)

    # Two-tailed: double one-sided tail, bounded by 1.0
    return min(1.0, 2.0 * p_val)


def mcnemar_test(
    model_a_results: List[bool],
    model_b_results: List[bool],
    alpha: float = 0.05
) -> Dict[str, Any]:
    """Perform McNemar's test on paired evaluation outcomes.

    Contingency table:
                Model B Pass    Model B Fail
    Model A Pass      a               b
    Model A Fail      c               d
    """
    if len(model_a_results) != len(model_b_results):
        raise ValueError("Results lists must be of identical length for paired test")

    n = len(model_a_results)
    if n == 0:
        return {
            "n": 0,
            "p_value": 1.0,
            "statistically_significant": False,
            "verdict": "Difference not statistically significant (N=0)"
        }

    a = b = c = d = 0
    for r_a, r_b in zip(model_a_results, model_b_results):
        if r_a and r_b:
            a += 1
        elif r_a and not r_b:
            b += 1
        elif not r_a and r_b:
            c += 1
        else:
            d += 1

    discordant = b + c
    if discordant == 0:
        return {
            "n": n,
            "table": {"both_pass": a, "a_only": b, "b_only": c, "both_fail": d},
            "discordant_pairs": 0,
            "p_value": 1.0,
            "alpha": alpha,
            "statistically_significant": False,
            "verdict": "Difference not statistically significant (identical performance on all tasks)"
        }

    # Small sample exact binomial test vs large sample chi-squared
    if discordant < 25:
        p_val = exact_binomial_two_tailed(min(b, c), discordant, 0.5)
        test_type = "Exact Binomial Test"
        stat = float(min(b, c))
    else:
        # McNemar's chi-squared with continuity correction: (|b - c| - 1)^2 / (b + c)
        chi2 = ((abs(b - c) - 1.0) ** 2) / float(discordant)
        # For df=1, p-value from chi2 is 2 * (1 - normal_cdf(sqrt(chi2)))
        z = math.sqrt(chi2)
        p_val = 2.0 * (1.0 - normal_cdf(z))
        test_type = "McNemar Chi-Square (Continuity Corrected)"
        stat = round(chi2, 4)

    p_val = max(0.0, min(1.0, float(round(p_val, 6))))
    is_sig = bool(p_val < alpha)
    verdict = (
        f"Statistically significant difference (p = {p_val:.4f} < {alpha})"
        if is_sig
        else f"Difference not statistically significant (p = {p_val:.4f} >= {alpha})"
    )

    return {
        "n": n,
        "table": {"both_pass": a, "a_only": b, "b_only": c, "both_fail": d},
        "discordant_pairs": discordant,
        "statistic": stat,
        "test_type": test_type,
        "p_value": p_val,
        "alpha": alpha,
        "statistically_significant": is_sig,
        "verdict": verdict
    }


def paired_permutation_test(
    scores_a: List[float],
    scores_b: List[float],
    num_permutations: int = 10000,
    alpha: float = 0.05
) -> Dict[str, Any]:
    """Paired two-tailed permutation test for continuous or binary task scores."""
    if len(scores_a) != len(scores_b):
        raise ValueError("Score lists must have matching length")

    n = len(scores_a)
    if n == 0:
        return {"p_value": 1.0, "statistically_significant": False, "verdict": "Difference not statistically significant"}

    diffs = [a - b for a, b in zip(scores_a, scores_b)]
    obs_diff = sum(diffs) / n

    if abs(obs_diff) < 1e-9:
        return {
            "n": n,
            "observed_mean_diff": 0.0,
            "p_value": 1.0,
            "statistically_significant": False,
            "verdict": "Difference not statistically significant (zero mean difference)"
        }

    # Monte Carlo sign-flip permutations
    count_extreme = 0
    rng = random.Random(42)  # Deterministic seed for reproducible tests
    for _ in range(num_permutations):
        perm_sum = sum(d if rng.random() < 0.5 else -d for d in diffs)
        if abs(perm_sum / n) >= abs(obs_diff) - 1e-9:
            count_extreme += 1

    p_val = max(1.0 / num_permutations, float(round(count_extreme / num_permutations, 5)))
    is_sig = bool(p_val < alpha)
    verdict = (
        f"Statistically significant difference (p = {p_val:.4f} < {alpha})"
        if is_sig
        else f"Difference not statistically significant (p = {p_val:.4f} >= {alpha})"
    )

    return {
        "n": n,
        "observed_mean_diff": round(obs_diff, 4),
        "num_permutations": num_permutations,
        "p_value": p_val,
        "alpha": alpha,
        "statistically_significant": is_sig,
        "verdict": verdict
    }


if __name__ == "__main__":
    # Example comparison
    model_1 = [True] * 14 + [False] * 6
    model_2 = [True] * 9 + [False] * 11
    res = mcnemar_test(model_1, model_2)
    print("Paired McNemar Test Result:")
    print(json.dumps(res, indent=2))
