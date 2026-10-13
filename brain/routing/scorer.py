"""brain/routing/scorer.py — Expected Utility Scorer and Cold-Start Quality Scorer.

Provides:
1. ExpectedUtilityScorer:
   Balances empirical measured quality, TTFT (latency), cost, reliability,
   and prompt cache affinity with confidence intervals and dynamic hyperparameters.
2. ModelScorer:
   Manages Bayesian Beta-Binomial model quality scores, cold-start priors,
   early stopping, and bandit exploration bonuses.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from brain.routing.profiles import RequirementProfile, SoftObjectives
from brain.routing.hyperparameters import get_hyperparameter


# ============================================================================
# 1. Expected Utility Data Models & Scorer
# ============================================================================

class CandidateMetrics(BaseModel):
    model_id: str
    provider: str
    route_id: str
    context_window: int = 128000
    pricing: Dict[str, float] = Field(default_factory=dict)
    capabilities: Dict[str, bool] = Field(default_factory=dict)
    privacy_policy: str = "zero_retention"
    measured_quality: float = 0.70  # Empirical quality benchmark [0.0, 1.0]
    measured_ttft_ms: float = 400.0  # Empirical TTFT in ms
    success_count: int = 10
    failure_count: int = 0
    is_pinned: bool = False
    is_banned: bool = False
    is_cooldown: bool = False
    cooldown_remaining_s: float = 0.0


class ScoredCandidate(BaseModel):
    metrics: CandidateMetrics
    utility_score: float
    quality_score: float
    ttft_score: float
    cost_score: float
    reliability_score: float
    cache_affinity_bonus: float
    ci_lower: float
    ci_upper: float
    confidence: float
    estimated_cost_usd: float
    explanation: str


class ExpectedUtilityScorer:
    """Calculates expected utility scores for route candidates against a profile."""

    def __init__(
        self,
        cache_affinity_bonus: Optional[float] = None,
        target_max_ttft_ms: Optional[float] = None,
        pinned_bonus: Optional[float] = None,
    ) -> None:
        self._cache_affinity_bonus = cache_affinity_bonus
        self._target_max_ttft_ms = target_max_ttft_ms
        self._pinned_bonus = pinned_bonus

    @property
    def cache_affinity_bonus(self) -> float:
        if self._cache_affinity_bonus is not None:
            return self._cache_affinity_bonus
        return float(get_hyperparameter("cache_affinity_bonus", default=0.15))

    @property
    def target_max_ttft_ms(self) -> float:
        if self._target_max_ttft_ms is not None:
            return self._target_max_ttft_ms
        return float(get_hyperparameter("target_max_ttft_ms", default=3000.0))

    @property
    def pinned_bonus(self) -> float:
        if self._pinned_bonus is not None:
            return self._pinned_bonus
        return float(get_hyperparameter("pinned_model_bonus", default=0.25))

    def estimate_cost(
        self, metrics: CandidateMetrics, prompt_tokens: int = 500, est_completion_tokens: int = 400
    ) -> float:
        pricing = metrics.pricing or {}
        in_p = pricing.get("input_per_million", 0.0)
        out_p = pricing.get("output_per_million", 0.0)
        in_cost = (prompt_tokens / 1_000_000.0) * in_p
        out_cost = (est_completion_tokens / 1_000_000.0) * out_p
        return round(in_cost + out_cost, 6)

    def score_candidate(
        self,
        candidate: CandidateMetrics,
        profile: RequirementProfile,
        prompt_tokens: int = 500,
        session_active_model: Optional[str] = None,
    ) -> ScoredCandidate:
        weights: SoftObjectives = profile.soft_objectives.normalized()

        # 1. Bayesian Quality with Beta prior (alpha=2*q, beta=2*(1-q))
        total_trials = candidate.success_count + candidate.failure_count
        prior_alpha = 2.0 * candidate.measured_quality
        prior_beta = 2.0 * (1.0 - candidate.measured_quality)
        post_alpha = prior_alpha + candidate.success_count
        post_beta = prior_beta + candidate.failure_count
        post_total = post_alpha + post_beta

        q_mean = post_alpha / post_total if post_total > 0 else candidate.measured_quality
        variance = (post_alpha * post_beta) / ((post_total ** 2) * (post_total + 1.0))
        std_err = math.sqrt(max(1e-6, variance))

        ci_lower = max(0.0, round(q_mean - 1.96 * std_err, 4))
        ci_upper = min(1.0, round(q_mean + 1.96 * std_err, 4))
        confidence = max(0.1, min(1.0, round(1.0 - 2.0 * std_err, 4)))

        # 2. TTFT score: normalized exponential or linear decay
        ttft = max(10.0, candidate.measured_ttft_ms)
        ttft_score = max(0.0, min(1.0, round(1.0 - (ttft / self.target_max_ttft_ms), 4)))

        # 3. Cost score: normalized non-linear decay
        est_cost = self.estimate_cost(candidate, prompt_tokens=prompt_tokens)
        cost_score = round(1.0 / (1.0 + est_cost * 100.0), 4)

        # 4. Reliability score
        if total_trials > 0:
            rel_score = round(candidate.success_count / total_trials, 4)
        else:
            rel_score = 0.90
        if candidate.is_cooldown:
            rel_score = 0.0

        # 5. Cache affinity bonus
        cache_bonus = 0.0
        if session_active_model and session_active_model == candidate.model_id:
            cache_bonus = self.cache_affinity_bonus

        # 6. Combined utility
        raw_utility = (
            weights.quality * q_mean
            + weights.ttft * ttft_score
            + weights.cost * cost_score
            + weights.reliability * rel_score
            + cache_bonus
        )
        if candidate.is_pinned:
            raw_utility += self.pinned_bonus

        utility = round(raw_utility, 4)

        reason = (
            f"Quality: {q_mean:.2f} (w={weights.quality}), "
            f"TTFT: {ttft:.0f}ms (score={ttft_score:.2f}, w={weights.ttft}), "
            f"Cost: ${est_cost:.5f} (score={cost_score:.2f}, w={weights.cost}), "
            f"Rel: {rel_score:.2f} (w={weights.reliability})"
        )
        if cache_bonus > 0:
            reason += f" + CacheAffinity({cache_bonus})"
        if candidate.is_pinned:
            reason += f" + Pinned({self.pinned_bonus})"

        return ScoredCandidate(
            metrics=candidate,
            utility_score=utility,
            quality_score=round(q_mean, 4),
            ttft_score=ttft_score,
            cost_score=cost_score,
            reliability_score=rel_score,
            cache_affinity_bonus=cache_bonus,
            ci_lower=ci_lower,
            ci_upper=ci_upper,
            confidence=confidence,
            estimated_cost_usd=est_cost,
            explanation=reason,
        )

    def score_all(
        self,
        candidates: List[CandidateMetrics],
        profile: RequirementProfile,
        prompt_tokens: int = 500,
        session_active_model: Optional[str] = None,
    ) -> List[ScoredCandidate]:
        scored = [
            self.score_candidate(
                c,
                profile=profile,
                prompt_tokens=prompt_tokens,
                session_active_model=session_active_model,
            )
            for c in candidates
        ]
        # Sort by utility score descending
        scored.sort(key=lambda x: x.utility_score, reverse=True)
        return scored


# ============================================================================
# 2. Cold-Start Model Scorer (Requirement 7)
# ============================================================================

@dataclass
class QualityScore:
    canonical_id: str
    alpha: float
    beta: float
    samples_count: int
    mean_quality: float
    variance: float
    ci_lower: float
    ci_upper: float
    is_cold_start: bool
    exploration_bonus: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class ModelScorer:
    """Manages Bayesian Beta-Binomial model quality scores, cold-start priors,

    early stopping, and bandit exploration bonuses.
    """

    VENDOR_TIER_PRIORS: Dict[str, float] = {
        "openai": 0.86,
        "anthropic": 0.88,
        "google": 0.84,
        "deepseek": 0.83,
        "meta": 0.80,
        "qwen": 0.81,
        "mistralai": 0.79,
        "zhipu": 0.77,
        "minimax": 0.76,
        "cohere": 0.75,
        "xai": 0.82,
    }

    @property
    def DEFAULT_VENDOR_PRIOR(self) -> float:
        return float(get_hyperparameter("default_vendor_prior", default=0.72))

    @property
    def COLD_START_PSEUDOCOUNT(self) -> float:
        return float(get_hyperparameter("cold_start_pseudocount", default=4.0))

    @property
    def EARLY_STOPPING_CI_WIDTH(self) -> float:
        return float(get_hyperparameter("early_stopping_ci_width", default=0.18))

    def __init__(self, exploration_weight: float = 0.35, exploration_budget_usd: float = 5.0):
        self.exploration_weight = exploration_weight
        self.exploration_budget_usd = exploration_budget_usd
        self.scores: Dict[str, QualityScore] = {}
        self.total_routing_events: int = 0

    def compute_cold_start_prior(
        self,
        vendor: str,
        family: str,
        parameter_size: Optional[str] = None,
    ) -> Tuple[float, float]:
        base_p = self.VENDOR_TIER_PRIORS.get(vendor.lower(), self.DEFAULT_VENDOR_PRIOR)

        # Scale adjustment
        scale_adj = 0.0
        if parameter_size:
            s_lower = parameter_size.lower()
            try:
                num = float(s_lower.replace("b", "").replace("m", ""))
                if "b" in s_lower:
                    if num >= 70:
                        scale_adj = 0.06
                    elif num >= 20:
                        scale_adj = 0.03
                    elif num <= 7:
                        scale_adj = -0.05
                elif "m" in s_lower:
                    scale_adj = -0.15
            except ValueError:
                pass

        p = max(0.40, min(0.95, base_p + scale_adj))
        n_0 = self.COLD_START_PSEUDOCOUNT
        alpha_0 = p * n_0
        beta_0 = (1.0 - p) * n_0
        return alpha_0, beta_0

    def get_or_create_score(
        self,
        canonical_id: str,
        vendor: str = "community",
        family: str = "generic",
        parameter_size: Optional[str] = None,
    ) -> QualityScore:
        if canonical_id in self.scores:
            return self.scores[canonical_id]

        alpha_0, beta_0 = self.compute_cold_start_prior(vendor, family, parameter_size)
        score = self._build_score(
            canonical_id=canonical_id,
            alpha=alpha_0,
            beta=beta_0,
            samples_count=0,
            is_cold_start=True,
            metadata={
                "vendor": vendor,
                "family": family,
                "parameter_size": parameter_size,
                "prior_p": alpha_0 / (alpha_0 + beta_0),
            },
        )
        self.scores[canonical_id] = score
        return score

    def update_with_outcome(
        self,
        canonical_id: str,
        success: bool,
        vendor: str = "community",
        family: str = "generic",
        parameter_size: Optional[str] = None,
    ) -> QualityScore:
        curr = self.get_or_create_score(canonical_id, vendor, family, parameter_size)
        new_alpha = curr.alpha + (1.0 if success else 0.0)
        new_beta = curr.beta + (0.0 if success else 1.0)
        new_samples = curr.samples_count + 1
        self.total_routing_events += 1

        updated = self._build_score(
            canonical_id=canonical_id,
            alpha=new_alpha,
            beta=new_beta,
            samples_count=new_samples,
            is_cold_start=False,
            metadata=curr.metadata,
        )
        self.scores[canonical_id] = updated
        return updated

    def record_feedback(
        self,
        canonical_id: str,
        success: bool,
        vendor: str = "community",
        family: str = "generic",
        parameter_size: Optional[str] = None,
    ) -> QualityScore:
        """Alias for update_with_outcome — preferred API for test and service code."""
        return self.update_with_outcome(canonical_id, success, vendor, family, parameter_size)

    def can_early_stop(self, canonical_id: str) -> bool:
        if canonical_id not in self.scores:
            return False
        score = self.scores[canonical_id]
        if score.samples_count < 3:
            return False
        ci_width = score.ci_upper - score.ci_lower
        return ci_width <= self.EARLY_STOPPING_CI_WIDTH

    def compute_exploration_bonus(
        self,
        samples_count: int,
        variance: float,
        is_cold_start: bool,
    ) -> float:
        t = max(1, self.total_routing_events)
        n = max(1, samples_count)
        uncertainty = math.sqrt(variance)

        if is_cold_start or samples_count == 0:
            bonus = self.exploration_weight * (uncertainty * 2.0 + 0.20)
        else:
            decay_factor = math.sqrt(math.log(t + 1) / n)
            bonus = self.exploration_weight * min(0.35, uncertainty * decay_factor)

        return round(bonus, 4)

    def _build_score(
        self,
        canonical_id: str,
        alpha: float,
        beta: float,
        samples_count: int,
        is_cold_start: bool,
        metadata: Dict[str, Any],
    ) -> QualityScore:
        total = alpha + beta
        mean = alpha / total
        var = (alpha * beta) / ((total ** 2) * (total + 1.0))
        std_dev = math.sqrt(var)

        ci_lower = max(0.0, mean - 1.96 * std_dev)
        ci_upper = min(1.0, mean + 1.96 * std_dev)

        bonus = self.compute_exploration_bonus(samples_count, var, is_cold_start)

        return QualityScore(
            canonical_id=canonical_id,
            alpha=round(alpha, 4),
            beta=round(beta, 4),
            samples_count=samples_count,
            mean_quality=round(mean, 4),
            variance=round(var, 6),
            ci_lower=round(ci_lower, 4),
            ci_upper=round(ci_upper, 4),
            is_cold_start=is_cold_start,
            exploration_bonus=bonus,
            metadata=metadata,
        )
