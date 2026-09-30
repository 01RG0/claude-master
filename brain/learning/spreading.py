# brain/learning/spreading.py
"""
Priority-Queue BFS Spreading Activation.

Ported algorithm (MIT, clean-room) from:
  nhadaututtheky/neural-memory  (MIT)
  OSU-NLP-Group/HippoRAG        (MIT)

Algorithm (research/track-2-neuro-memory.md §5.2 / shortlist.md §5):
  1. Seed nodes start at score 1.0.
  2. Max-heap (min-heap with negated scores) priority queue.
  3. For each dequeued (score, node, hop):
       - Skip if already visited (refractory).
       - Skip if hop > max_hops or score < diminishing_threshold.
       - For each outgoing edge (target, weight, role, access_count):
           role_mult = ROLE_MULTIPLIERS[role]
           if role_mult == 0.0: skip
           myelin = 1.0 + min(0.15, 0.05 · ln(1 + access_count))
           child_score = parent_score · weight · role_mult · myelin
           if child_score >= min_weight and child_score > existing best:
               update results[target] and push to heap.
  4. Early exit when top-of-heap score < diminishing_threshold.
  5. Return {node_id: activation_score}.

'store' duck-typed interface requires:
    get_outgoing_edges(source_id, min_weight=0.0) -> list[dict]
        Each dict: {target_id, weight, role, access_count}
"""

import heapq
import math


class SpreadingActivation:
    """Priority-queue BFS spreading activation over the brain graph."""

    ROLE_MULTIPLIERS: dict[str, float] = {
        # Causal / sequential
        "causes": 1.3,
        "caused_by": 1.3,
        "leads_to": 1.3,
        "causal": 1.3,
        # Reinforcement
        "reinforces": 1.2,
        "enables": 1.2,
        "resolved_by": 1.2,
        "reinforcement": 1.2,
        # Supersession
        "supersedes": 1.1,
        # Structural / neutral
        "defines": 1.0,
        "depends_on": 1.0,
        "contains": 1.0,
        "member_of": 1.0,
        "structural": 1.0,
        # Lateral (mild damping)
        "lateral": 0.85,
        "related_to": 0.85,
        "co_occurs": 0.85,
        # Contradicts — blocks propagation completely
        "contradicts": 0.0,
        # Passive audit links — block propagation
        "passive": 0.0,
        "audit_log": 0.0,
    }

    def activate(
        self,
        store,
        seed_ids: list[str],
        max_hops: int = 3,
        min_weight: float = 0.1,
        max_nodes: int = 50,
        diminishing_threshold: float = 0.05,
    ) -> dict[str, float]:
        """Spread activation from seed nodes through the graph.

        Args:
            store: Duck-typed store exposing get_outgoing_edges().
            seed_ids: List of node IDs to seed with activation 1.0.
            max_hops: Maximum BFS depth.
            min_weight: Minimum edge weight to traverse.
            max_nodes: Maximum number of nodes to include in results.
            diminishing_threshold: Early-exit when top score < this.

        Returns:
            Dict mapping node_id -> best activation score.
        """
        results: dict[str, float] = {}
        visited: set[str] = set()

        # Max-heap (negated scores)
        heap: list[tuple[float, str, int]] = []

        # Initialise seeds at score 1.0
        for seed in seed_ids:
            results[seed] = 1.0
            heapq.heappush(heap, (-1.0, seed, 0))

        while heap and len(results) < max_nodes:
            neg_score, node_id, hop = heapq.heappop(heap)
            score = -neg_score

            # Early exit: diminishing returns
            if score < diminishing_threshold:
                break

            # Refractory: skip already fully processed nodes
            if node_id in visited:
                continue
            visited.add(node_id)

            # Depth limit
            if hop >= max_hops:
                continue

            # Myelination boost for current node: based on its own access history
            # (we'll apply it per-edge using the target's access_count instead, per spec)

            # Traverse outgoing edges
            edges = store.get_outgoing_edges(node_id, min_weight=min_weight)
            for edge in edges:
                target_id: str = edge["target_id"]
                edge_weight: float = edge["weight"]
                role: str = edge.get("role", "lateral")
                access_count: int = edge.get("access_count", 0)

                # Skip already-visited targets (refractory)
                if target_id in visited:
                    continue

                # Role multiplier — 0.0 blocks propagation
                role_mult = self.ROLE_MULTIPLIERS.get(role.lower(), 1.0)
                if role_mult == 0.0:
                    continue

                # Myelination conductance boost
                myelin = 1.0 + min(0.15, 0.05 * math.log1p(access_count))

                child_score = score * edge_weight * role_mult * myelin

                if child_score < diminishing_threshold:
                    continue

                # Only update if this path gives a better score
                if child_score > results.get(target_id, 0.0):
                    results[target_id] = child_score
                    heapq.heappush(heap, (-child_score, target_id, hop + 1))

        return results
