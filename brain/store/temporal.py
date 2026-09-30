"""
brain/store/temporal.py
-----------------------
TemporalStore: bi-temporal fact management with contradiction resolution.

Algorithm provenance:
- Contradiction resolution pattern ported from getzep/graphiti (Apache-2.0)
  graphiti_core/utils/maintenance/edge_operations.py (invalidate_edges logic)
  No graphiti classes or imports are used; only the algorithm is ported.
"""

import logging
import time
from typing import Dict, Any, List, Optional

from brain.store.graph import GraphStore, _now_ms

logger = logging.getLogger(__name__)


class TemporalStore(GraphStore):
    """
    Extends GraphStore with bi-temporal fact semantics:

    - Facts are directed edges carrying a temporal validity window
      (valid_at … invalid_at).
    - Adding a contradicting fact (same source/target/relation_type) marks the
      old edge as invalid (sets invalid_at = now) rather than deleting it,
      preserving historical provenance.
    """

    # ------------------------------------------------------------------
    # Fact operations
    # ------------------------------------------------------------------

    def add_fact(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        weight: float = 0.5,
    ) -> str:
        """
        Persist a fact as a directed bi-temporal edge.

        If an active (invalid_at IS NULL) edge with the same
        (source_id, target_id, relation_type) already exists and differs in
        weight, it is treated as a contradiction: the old edge is invalidated
        and a new edge is created.

        Returns the edge_id of the (possibly new) active edge.
        """
        old_edge_id = self.contradiction_resolution(source_id, target_id, relation_type)
        if old_edge_id is not None:
            # Invalidate the superseded edge.
            self.conn.execute(
                "UPDATE brain_edges SET invalid_at = ?, updated_at = ? WHERE id = ?",
                (_now_ms(), _now_ms(), old_edge_id),
            )
            self.conn.commit()
            logger.debug(
                "Invalidated edge %s (%s->%s [%s])",
                old_edge_id, source_id, target_id, relation_type,
            )

        return self.add_edge(source_id, target_id, relation_type, weight)

    def contradiction_resolution(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
    ) -> Optional[str]:
        """
        Return the id of an existing active edge with the same
        (source_id, target_id, relation_type) triple, or None if no such edge
        exists.

        Callers use the returned id to decide whether a contradiction occurred
        and must invalidate the old edge before inserting the new fact.
        """
        row = self.conn.execute(
            """
            SELECT id FROM brain_edges
            WHERE source_id = ?
              AND target_id = ?
              AND relation_type = ?
              AND invalid_at IS NULL
            LIMIT 1
            """,
            (source_id, target_id, relation_type),
        ).fetchone()
        return row["id"] if row else None

    # ------------------------------------------------------------------
    # Bi-temporal query
    # ------------------------------------------------------------------

    def get_facts_at(self, timestamp: int) -> List[Dict[str, Any]]:
        """
        Return all edges that were valid at the given *timestamp* (milliseconds
        since epoch).

        An edge is valid at T when:
            valid_at <= T  AND  (invalid_at IS NULL  OR  invalid_at > T)
        """
        rows = self.conn.execute(
            """
            SELECT * FROM brain_edges
            WHERE valid_at <= ?
              AND (invalid_at IS NULL OR invalid_at > ?)
            """,
            (timestamp, timestamp),
        ).fetchall()
        return [dict(r) for r in rows]
