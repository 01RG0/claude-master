# brain/learning/fsrs.py
"""
FSRS-5 DSR Power-Law Forgetting Engine.

Ported algorithm (MIT, clean-room) from:
  open-spaced-repetition/py-fsrs  (MIT)

Formulas (research/track-2-neuro-memory.md §4.3 / shortlist.md §4):
  R(t, S) = (1 + FACTOR · t/S)^(-0.5)
  FACTOR   = 19/81  (FSRS-5 constant)

  Stability update on success:
    S_new = S · (e^(0.9·R) + 1)

  Stability update on failure:
    S_new = max(0.1, S · 0.5 · (2 - R))

  Difficulty update:
    success: D_new = max(0.1, D - 0.05)
    failure: D_new = min(1.0, D + 0.1)

  Prune trigger:
    R(t, S) < threshold
"""

import math


class FSRSDecay:
    """FSRS-5 memory-decay calculations."""

    FACTOR: float = 19.0 / 81.0  # ≈ 0.2346

    # -----------------------------------------------------------------
    # Core formula
    # -----------------------------------------------------------------

    def retrievability(self, t_days: float, stability: float) -> float:
        """Probability of correct recall at time t given stability S.

        R(t, S) = (1 + FACTOR · t/S)^(-0.5)

        Clamped to [0.0, 1.0].

        Args:
            t_days: Days elapsed since last review.
            stability: FSRS stability (memory half-life in days).

        Returns:
            Retrievability ∈ [0.0, 1.0].
        """
        if t_days <= 0.0:
            return 1.0
        if stability <= 0.0:
            return 0.0
        r = (1.0 + self.FACTOR * t_days / stability) ** (-0.5)
        return max(0.0, min(1.0, r))

    # -----------------------------------------------------------------
    # State updates
    # -----------------------------------------------------------------

    def update_stability(
        self,
        stability: float,
        retrievability: float,
        success: bool,
    ) -> float:
        """Compute updated stability after a review event.

        Success: S_new = S · (e^(0.9·R) + 1)
        Failure: S_new = max(0.1, S · 0.5 · (2 − R))

        Args:
            stability: Current FSRS stability (days).
            retrievability: Retrievability R at review time.
            success: True if recall succeeded, False otherwise.

        Returns:
            New stability value.
        """
        if success:
            return stability * (math.exp(0.9 * retrievability) + 1.0)
        else:
            return max(0.1, stability * 0.5 * (2.0 - retrievability))

    def update_difficulty(self, difficulty: float, success: bool) -> float:
        """Compute updated difficulty after a review event.

        Success: D_new = max(0.1, D − 0.05)
        Failure: D_new = min(1.0, D + 0.1)

        Args:
            difficulty: Current FSRS difficulty ∈ [0.1, 1.0].
            success: True if recall succeeded.

        Returns:
            New difficulty value.
        """
        if success:
            return max(0.1, difficulty - 0.05)
        else:
            return min(1.0, difficulty + 0.1)

    # -----------------------------------------------------------------
    # Pruning decision
    # -----------------------------------------------------------------

    def should_prune(
        self,
        stability: float,
        days_since_access: float,
        threshold: float = 0.05,
    ) -> bool:
        """Determine if a memory node should be pruned.

        A node is pruned when its retrievability falls below the threshold.

        Args:
            stability: FSRS stability of the node.
            days_since_access: Days elapsed since node was last accessed.
            threshold: Minimum acceptable retrievability.

        Returns:
            True if the node should be pruned.
        """
        r = self.retrievability(t_days=days_since_access, stability=stability)
        return r < threshold
