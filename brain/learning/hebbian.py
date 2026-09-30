# brain/learning/hebbian.py
"""
Three-Factor Neuromodulated Hebbian Learning with headroom saturation
and competitive synaptic budget normalisation.

Formula (from research/track-2-neuro-memory.md §5.1):
    Δw = η_eff · R · a_pre · a_post · (W_MAX − w)
    η_eff = ETA · (1 + 0.2 · |R|)          # neuromodulation boost

Clamping: w ∈ [W_MIN, W_MAX]
Normalisation: if Σ outgoing > W_MAX_OUTGOING, scale all down.

The 'store' argument is duck-typed – any object exposing:
    get_edge_weight(src, tgt) -> float | None
    set_edge_weight(src, tgt, weight) -> None
    get_all_outgoing_weights(src) -> dict[str, float]
    set_all_outgoing_weights(src, weights) -> None
"""


class HebbianUpdater:
    W_MAX: float = 1.0
    W_MIN: float = 0.0
    ETA: float = 0.1
    W_MAX_OUTGOING: float = 5.0

    # -----------------------------------------------------------------
    # Core update
    # -----------------------------------------------------------------

    def update(
        self,
        store,
        source_id: str,
        target_id: str,
        pre_activation: float,
        post_activation: float,
        reward: float,
    ) -> float:
        """Compute and apply Δw; return Δw.

        Args:
            store: Duck-typed store interface.
            source_id: Pre-synaptic node id.
            target_id: Post-synaptic node id.
            pre_activation: Activation level of pre-synaptic node ∈ [0, 1].
            post_activation: Activation level of post-synaptic node ∈ [0, 1].
            reward: Neuromodulator signal ∈ [-1, +1].

        Returns:
            delta_w – signed weight change applied.
        """
        current_w = store.get_edge_weight(source_id, target_id)
        if current_w is None:
            current_w = 0.0

        eta_eff = self.ETA * (1.0 + 0.2 * abs(reward))
        delta_w = eta_eff * reward * pre_activation * post_activation * (
            self.W_MAX - current_w
        )

        new_w = max(self.W_MIN, min(self.W_MAX, current_w + delta_w))
        store.set_edge_weight(source_id, target_id, new_w)

        self._normalize_outgoing(store, source_id)
        return new_w - current_w  # actual applied delta

    # -----------------------------------------------------------------
    # Convenience wrappers
    # -----------------------------------------------------------------

    def ltp(self, store, source_id: str, target_id: str, strength: float = 0.8) -> float:
        """Long-Term Potentiation: reward = +1."""
        return self.update(
            store, source_id, target_id,
            pre_activation=strength,
            post_activation=strength,
            reward=1.0,
        )

    def ltd(self, store, source_id: str, target_id: str, strength: float = 0.8) -> float:
        """Long-Term Depression: reward = -1."""
        return self.update(
            store, source_id, target_id,
            pre_activation=strength,
            post_activation=strength,
            reward=-1.0,
        )

    def downscale_all(self, store, factor: float = 0.95) -> None:
        """Synaptic Homeostasis (SHY): globally scale all outgoing weights.

        Args:
            store: Must additionally expose get_all_edges() ->
                   list[tuple[src, tgt, w]], or the caller can pass
                   a specialised store. For the generic duck-typed
                   interface we rely on get_all_outgoing_weights per
                   source – callers must manage the source set.
        """
        # Generic fallback: if store exposes get_all_edges
        if hasattr(store, "get_all_edges"):
            sources = {src for src, _tgt, _w in store.get_all_edges()}
            for src in sources:
                weights = store.get_all_outgoing_weights(src)
                scaled = {tgt: max(self.W_MIN, w * factor) for tgt, w in weights.items()}
                store.set_all_outgoing_weights(src, scaled)

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    def _normalize_outgoing(self, store, source_id: str) -> None:
        """Scale outgoing weights if their sum exceeds W_MAX_OUTGOING."""
        weights = store.get_all_outgoing_weights(source_id)
        total = sum(weights.values())
        if total > self.W_MAX_OUTGOING and total > 0.0:
            scale = self.W_MAX_OUTGOING / total
            normalized = {tgt: w * scale for tgt, w in weights.items()}
            store.set_all_outgoing_weights(source_id, normalized)
