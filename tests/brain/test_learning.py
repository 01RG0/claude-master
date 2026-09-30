"""
Tests for brain/learning modules (B2 – Learning Engine).

Mock store interface (duck-typed):
  store.get_edge_weight(source_id, target_id) -> float | None
  store.set_edge_weight(source_id, target_id, weight) -> None
  store.get_all_outgoing_weights(source_id) -> dict[str, float]
  store.set_all_outgoing_weights(source_id, weights) -> None
  store.get_outgoing_edges(source_id, min_weight=0.0) -> list[dict]
      Each dict has keys: target_id, weight, role, access_count
"""

import math
import pytest

# ---------------------------------------------------------------------------
# Pure in-memory mock store (no brain.store import)
# ---------------------------------------------------------------------------

class MockStore:
    """Minimal dict-backed store implementing the duck-typed edge interface."""

    def __init__(self):
        # (source_id, target_id) -> weight
        self._weights: dict[tuple[str, str], float] = {}
        # (source_id, target_id) -> edge metadata dict
        self._edges: dict[tuple[str, str], dict] = {}

    def get_edge_weight(self, source_id: str, target_id: str) -> float | None:
        return self._weights.get((source_id, target_id))

    def set_edge_weight(self, source_id: str, target_id: str, weight: float) -> None:
        self._weights[(source_id, target_id)] = weight
        if (source_id, target_id) not in self._edges:
            self._edges[(source_id, target_id)] = {
                "target_id": target_id,
                "weight": weight,
                "role": "lateral",
                "access_count": 1,
            }
        else:
            self._edges[(source_id, target_id)]["weight"] = weight

    def get_all_outgoing_weights(self, source_id: str) -> dict[str, float]:
        result = {}
        for (src, tgt), w in self._weights.items():
            if src == source_id:
                result[tgt] = w
        return result

    def set_all_outgoing_weights(self, source_id: str, weights: dict[str, float]) -> None:
        # Remove old outgoing for source_id then insert new values
        keys_to_remove = [(s, t) for (s, t) in self._weights if s == source_id]
        for k in keys_to_remove:
            del self._weights[k]
            if k in self._edges:
                del self._edges[k]
        for tgt, w in weights.items():
            self.set_edge_weight(source_id, tgt, w)

    def add_edge(self, source_id: str, target_id: str, weight: float,
                 role: str = "lateral", access_count: int = 1) -> None:
        """Helper for tests to set up directed edges with metadata."""
        self._weights[(source_id, target_id)] = weight
        self._edges[(source_id, target_id)] = {
            "target_id": target_id,
            "weight": weight,
            "role": role,
            "access_count": access_count,
        }

    def get_outgoing_edges(self, source_id: str, min_weight: float = 0.0) -> list[dict]:
        results = []
        for (src, tgt), meta in self._edges.items():
            if src == source_id and meta["weight"] >= min_weight:
                results.append(dict(meta))
        return results

    def get_all_edges(self) -> list[tuple[str, str, float]]:
        """Return all (source, target, weight) tuples."""
        return [(s, t, w) for (s, t), w in self._weights.items()]


# ---------------------------------------------------------------------------
# Import the modules under test
# ---------------------------------------------------------------------------

from brain.learning.hebbian import HebbianUpdater
from brain.learning.fsrs import FSRSDecay
from brain.learning.spreading import SpreadingActivation


# ---------------------------------------------------------------------------
# HebbianUpdater tests
# ---------------------------------------------------------------------------

class TestHebbianLTP:
    def test_hebbian_ltp_increases_weight(self):
        """Weight goes up on reward=+1 (LTP)."""
        store = MockStore()
        store.set_edge_weight("A", "B", 0.3)
        updater = HebbianUpdater()
        delta = updater.ltp(store, "A", "B", strength=0.8)
        new_w = store.get_edge_weight("A", "B")
        assert new_w > 0.3, f"LTP should increase weight; got {new_w}"
        assert delta > 0, f"delta_w should be positive; got {delta}"


class TestHebbianLTD:
    def test_hebbian_ltd_decreases_weight(self):
        """Weight goes down on reward=-1 (LTD)."""
        store = MockStore()
        store.set_edge_weight("A", "B", 0.6)
        updater = HebbianUpdater()
        delta = updater.ltd(store, "A", "B", strength=0.8)
        new_w = store.get_edge_weight("A", "B")
        assert new_w < 0.6, f"LTD should decrease weight; got {new_w}"
        assert delta < 0, f"delta_w should be negative; got {delta}"


class TestHebbianClamp:
    def test_hebbian_weight_clamped_upper(self):
        """Weight never exceeds W_MAX=1.0 even with extreme inputs."""
        store = MockStore()
        store.set_edge_weight("A", "B", 0.99)
        updater = HebbianUpdater()
        updater.update(store, "A", "B", pre_activation=1.0, post_activation=1.0, reward=1.0)
        new_w = store.get_edge_weight("A", "B")
        assert new_w <= HebbianUpdater.W_MAX, f"Weight exceeded W_MAX: {new_w}"

    def test_hebbian_weight_clamped_lower(self):
        """Weight never goes below W_MIN=0.0."""
        store = MockStore()
        store.set_edge_weight("A", "B", 0.01)
        updater = HebbianUpdater()
        updater.update(store, "A", "B", pre_activation=1.0, post_activation=1.0, reward=-1.0)
        new_w = store.get_edge_weight("A", "B")
        assert new_w >= HebbianUpdater.W_MIN, f"Weight went below W_MIN: {new_w}"

    def test_hebbian_weight_clamped(self):
        """Composite: weight stays in [W_MIN, W_MAX] across many updates."""
        store = MockStore()
        store.set_edge_weight("X", "Y", 0.5)
        updater = HebbianUpdater()
        for reward in [1.0, 1.0, 1.0, 1.0, -1.0, -1.0, -1.0]:
            updater.update(store, "X", "Y", 1.0, 1.0, reward)
            w = store.get_edge_weight("X", "Y")
            assert 0.0 <= w <= 1.0, f"Clamp violated: {w}"


class TestHebbianNormalization:
    def test_outgoing_weights_normalized_when_sum_exceeds_max(self):
        """After update, sum of outgoing weights should not exceed W_MAX_OUTGOING."""
        store = MockStore()
        # Pre-load 5 edges at 0.95 each → sum = 4.75; one ltp push should trigger normalisation
        for i in range(6):
            store.set_edge_weight("S", f"T{i}", 0.9)
        updater = HebbianUpdater()
        updater.update(store, "S", "T0", pre_activation=1.0, post_activation=1.0, reward=1.0)
        total = sum(store.get_all_outgoing_weights("S").values())
        assert total <= HebbianUpdater.W_MAX_OUTGOING + 1e-9, (
            f"Outgoing sum {total} exceeds W_MAX_OUTGOING {HebbianUpdater.W_MAX_OUTGOING}"
        )


# ---------------------------------------------------------------------------
# FSRSDecay tests
# ---------------------------------------------------------------------------

class TestFSRSRetrievability:
    def test_fsrs_retrievability_fresh(self):
        """R(0, S) should be 1.0 (just learned, no elapsed time)."""
        fsrs = FSRSDecay()
        r = fsrs.retrievability(t_days=0.0, stability=1.0)
        assert abs(r - 1.0) < 1e-9, f"R(0,1.0) expected 1.0, got {r}"

    def test_fsrs_retrievability_decays(self):
        """R(30, 1.0) < R(1, 1.0): retrievability must decay over time."""
        fsrs = FSRSDecay()
        r_1 = fsrs.retrievability(t_days=1.0, stability=1.0)
        r_30 = fsrs.retrievability(t_days=30.0, stability=1.0)
        assert r_30 < r_1, f"Expected r_30 < r_1; got {r_30:.4f} vs {r_1:.4f}"

    def test_fsrs_retrievability_clamped(self):
        """Retrievability must stay in [0, 1]."""
        fsrs = FSRSDecay()
        assert 0.0 <= fsrs.retrievability(0.0, 1.0) <= 1.0
        assert 0.0 <= fsrs.retrievability(1000.0, 0.1) <= 1.0


class TestFSRSUpdateStability:
    def test_stability_increases_on_success(self):
        fsrs = FSRSDecay()
        s_new = fsrs.update_stability(stability=1.0, retrievability=0.8, success=True)
        assert s_new > 1.0, f"Stability should increase on success; got {s_new}"

    def test_stability_decreases_on_failure(self):
        fsrs = FSRSDecay()
        s_new = fsrs.update_stability(stability=1.0, retrievability=0.8, success=False)
        assert s_new < 1.0, f"Stability should decrease on failure; got {s_new}"

    def test_stability_floor_on_failure(self):
        fsrs = FSRSDecay()
        s_new = fsrs.update_stability(stability=0.01, retrievability=0.9, success=False)
        assert s_new >= 0.1, f"Stability should not drop below 0.1; got {s_new}"


class TestFSRSUpdateDifficulty:
    def test_difficulty_decreases_on_success(self):
        fsrs = FSRSDecay()
        d_new = fsrs.update_difficulty(difficulty=0.5, success=True)
        assert d_new < 0.5

    def test_difficulty_increases_on_failure(self):
        fsrs = FSRSDecay()
        d_new = fsrs.update_difficulty(difficulty=0.5, success=False)
        assert d_new > 0.5

    def test_difficulty_clamps(self):
        fsrs = FSRSDecay()
        assert fsrs.update_difficulty(0.05, success=True) >= 0.1
        assert fsrs.update_difficulty(0.99, success=False) <= 1.0


class TestFSRSPrune:
    def test_fsrs_prune_trigger(self):
        """Low stability + long time → R falls below threshold → should_prune=True."""
        fsrs = FSRSDecay()
        # stability=0.1 days, 365 days since access → R ≈ 0
        result = fsrs.should_prune(stability=0.1, days_since_access=365.0, threshold=0.05)
        assert result is True, "Expected should_prune=True for very stale memory"

    def test_fsrs_no_prune_fresh(self):
        """Fresh memory should not be pruned."""
        fsrs = FSRSDecay()
        result = fsrs.should_prune(stability=10.0, days_since_access=1.0, threshold=0.05)
        assert result is False, "Fresh memory should not be pruned"


# ---------------------------------------------------------------------------
# SpreadingActivation tests
# ---------------------------------------------------------------------------

class TestSpreadingActivationBasic:
    def test_spreading_activation_basic(self):
        """3-node chain A->B->C; seed=[A]; A, B, C all returned with decreasing scores."""
        store = MockStore()
        store.add_edge("A", "B", weight=0.8, role="lateral", access_count=1)
        store.add_edge("B", "C", weight=0.8, role="lateral", access_count=1)

        sa = SpreadingActivation()
        results = sa.activate(store, seed_ids=["A"], max_hops=3, min_weight=0.01, max_nodes=50)

        assert "A" in results, "Seed A must be in results"
        assert "B" in results, "B should be activated"
        assert "C" in results, "C should be activated"
        assert results["A"] > results["B"], f"A({results['A']:.3f}) should > B({results['B']:.3f})"
        assert results["B"] > results["C"], f"B({results['B']:.3f}) should > C({results['C']:.3f})"

    def test_spreading_activation_seed_score_is_one(self):
        """Seed nodes start with activation score of 1.0."""
        store = MockStore()
        store.add_edge("A", "B", weight=0.5, role="lateral", access_count=0)
        sa = SpreadingActivation()
        results = sa.activate(store, seed_ids=["A"])
        assert abs(results["A"] - 1.0) < 1e-9, f"Seed score should be 1.0, got {results['A']}"


class TestSpreadingActivationRefractory:
    def test_spreading_activation_refractory(self):
        """No node should be visited (scored) more than once — no double-counting."""
        store = MockStore()
        # A -> B -> C -> A (cycle); refractory prevents infinite loop
        store.add_edge("A", "B", weight=0.9, role="lateral", access_count=1)
        store.add_edge("B", "C", weight=0.9, role="lateral", access_count=1)
        store.add_edge("C", "A", weight=0.9, role="lateral", access_count=1)

        sa = SpreadingActivation()
        results = sa.activate(store, seed_ids=["A"], max_hops=5)

        # All node_ids should be unique keys (dict guarantees that)
        # The score of A must not be inflated by the cycle
        assert results["A"] == 1.0, f"A score should remain 1.0 (seed), got {results['A']}"
        # B and C should have scores < 1.0 due to refractory on A
        assert results.get("B", 0.0) < 1.0
        assert results.get("C", 0.0) < 1.0


class TestSpreadingActivationRoleMultiplier:
    def test_spreading_activation_role_multiplier(self):
        """Causal edge score > lateral edge score from the same source with same weight."""
        store = MockStore()
        # S -> B (causal, 1.3x) and S -> C (lateral, 0.85x), same weight
        store.add_edge("S", "B", weight=0.5, role="causes", access_count=1)
        store.add_edge("S", "C", weight=0.5, role="lateral", access_count=1)

        sa = SpreadingActivation()
        results = sa.activate(store, seed_ids=["S"], max_hops=1, min_weight=0.0)

        score_b = results.get("B", 0.0)
        score_c = results.get("C", 0.0)
        assert score_b > score_c, (
            f"Causal edge to B ({score_b:.4f}) should score higher "
            f"than lateral edge to C ({score_c:.4f})"
        )

    def test_contradicts_role_blocks_propagation(self):
        """Contradicts edges (multiplier=0.0) must not propagate activation."""
        store = MockStore()
        store.add_edge("S", "D", weight=0.9, role="contradicts", access_count=1)

        sa = SpreadingActivation()
        results = sa.activate(store, seed_ids=["S"], max_hops=2)

        assert "D" not in results, "Contradicts edges should block propagation (D not activated)"


class TestSpreadingActivationMyelination:
    def test_myelination_boosts_high_access_node(self):
        """A node with high access_count should receive a myelination boost."""
        store_low = MockStore()
        store_high = MockStore()

        store_low.add_edge("S", "T", weight=0.5, role="lateral", access_count=0)
        store_high.add_edge("S", "T", weight=0.5, role="lateral", access_count=100)

        sa = SpreadingActivation()
        results_low = sa.activate(store_low, seed_ids=["S"], max_hops=1, min_weight=0.0)
        results_high = sa.activate(store_high, seed_ids=["S"], max_hops=1, min_weight=0.0)

        assert results_high.get("T", 0.0) >= results_low.get("T", 0.0), (
            "High access_count should produce equal or higher activation"
        )
