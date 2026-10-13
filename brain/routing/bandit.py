"""brain/routing/bandit.py — Bandit exploration with capped budget.

Allocates exploratory traffic to under-sampled or newly registered routes while
strictly enforcing a safety budget cap and avoiding degraded routes.
"""

from __future__ import annotations

import random
from typing import List, Optional
from pydantic import BaseModel, Field

from brain.routing.scorer import CandidateMetrics
from brain.routing.hyperparameters import get_hyperparameter


class BanditState(BaseModel):
    epsilon: float = Field(default_factory=lambda: float(get_hyperparameter("bandit_epsilon")))
    min_samples_threshold: int = Field(default_factory=lambda: int(get_hyperparameter("bandit_min_samples_threshold")))
    budget_cap_usd: float = Field(default_factory=lambda: float(get_hyperparameter("bandit_budget_cap_usd")))
    spent_usd: float = 0.0
    exploration_count: int = 0
    exploitation_count: int = 0


class BanditRouter:
    """Manages epsilon-greedy exploration for route discovery within a dollar budget."""

    def __init__(
        self,
        epsilon: Optional[float] = None,
        min_samples_threshold: Optional[int] = None,
        budget_cap_usd: Optional[float] = None,
        rng: Optional[random.Random] = None,
    ) -> None:
        eff_eps = epsilon if epsilon is not None else float(get_hyperparameter("bandit_epsilon"))
        eff_samples = min_samples_threshold if min_samples_threshold is not None else int(get_hyperparameter("bandit_min_samples_threshold"))
        eff_budget = budget_cap_usd if budget_cap_usd is not None else float(get_hyperparameter("bandit_budget_cap_usd"))

        self.state = BanditState(
            epsilon=eff_eps,
            min_samples_threshold=eff_samples,
            budget_cap_usd=eff_budget,
        )
        self.rng = rng or random.Random()

    def get_undersampled_candidates(
        self, candidates: List[CandidateMetrics]
    ) -> List[CandidateMetrics]:
        eligible = []
        for c in candidates:
            if c.is_banned or c.is_cooldown:
                continue
            total_samples = c.success_count + c.failure_count
            if total_samples < self.state.min_samples_threshold:
                eligible.append(c)
        return eligible

    def should_explore(
        self, candidates: List[CandidateMetrics], force_explore: bool = False
    ) -> bool:
        if self.state.spent_usd >= self.state.budget_cap_usd:
            return False

        undersampled = self.get_undersampled_candidates(candidates)
        if not undersampled:
            return False

        if force_explore:
            return True

        return self.rng.random() < self.state.epsilon

    def select_explore_candidate(
        self, candidates: List[CandidateMetrics]
    ) -> Optional[CandidateMetrics]:
        undersampled = self.get_undersampled_candidates(candidates)
        if not undersampled:
            return None
        # Select least-sampled candidate
        undersampled.sort(key=lambda c: (c.success_count + c.failure_count, -c.measured_quality))
        return undersampled[0]

    def record_decision(self, is_exploration: bool, cost_usd: float = 0.0) -> None:
        if is_exploration:
            self.state.exploration_count += 1
            self.state.spent_usd = round(self.state.spent_usd + cost_usd, 6)
        else:
            self.state.exploitation_count += 1
