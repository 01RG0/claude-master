"""
brain/store/graph.py
--------------------
GraphStore: bi-temporal node & edge CRUD on top of BrainDB.

Algorithm provenance:
- Bi-temporal edge model ported from getzep/graphiti (Apache-2.0)
  graphiti_core/edges.py & graphiti_core/utils/maintenance/edge_operations.py
  Only the data-model logic is ported; no graphiti runtime dependency.
"""

import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from brain.store.db import BrainDB

logger = logging.getLogger(__name__)


def _now_ms() -> int:
    """Return current UTC time as integer milliseconds since epoch."""
    return int(time.time() * 1000)


class GraphStore(BrainDB):
    """
    Node and edge CRUD with FTS5 sync and recursive CTE neighbour traversal.
    """

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

    def upsert_node(
        self,
        id: str,
        node_type: str,
        name: str,
        content: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Insert or replace a brain node, keeping FTS5 in sync.

        Returns the full node dict as stored.
        """
        now = _now_ms()
        tags_json = json.dumps(tags or [])

        # Check if node already exists to preserve created_at.
        existing = self.conn.execute(
            "SELECT created_at FROM brain_nodes WHERE id = ?", (id,)
        ).fetchone()
        created_at = existing["created_at"] if existing else now

        self.conn.execute(
            """
            INSERT INTO brain_nodes
                (id, node_type, name, content, tags, last_accessed_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                node_type        = excluded.node_type,
                name             = excluded.name,
                content          = excluded.content,
                tags             = excluded.tags,
                last_accessed_at = excluded.last_accessed_at
            """,
            (id, node_type, name, content, tags_json, now, created_at),
        )
        self.update_node_fts(id, name, content or "")
        self.conn.commit()
        return self.get_node(id)  # type: ignore[return-value]

    def get_node(self, id: str) -> Optional[Dict[str, Any]]:
        """Return node dict or None if not found."""
        row = self.conn.execute(
            "SELECT * FROM brain_nodes WHERE id = ?", (id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def update_node_fts(self, id: str, name: str, content: str) -> None:
        """
        Keep brain_nodes_fts virtual table in sync with the node row.

        FTS5 does not support ON CONFLICT, so we delete + re-insert.
        """
        self.conn.execute(
            "DELETE FROM brain_nodes_fts WHERE id = ?", (id,)
        )
        self.conn.execute(
            "INSERT INTO brain_nodes_fts (id, name, content) VALUES (?, ?, ?)",
            (id, name, content),
        )

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        weight: float = 0.5,
    ) -> str:
        """
        Insert a new bi-temporal directed edge.

        Returns the UUID edge_id.
        """
        edge_id = str(uuid.uuid4())
        now = _now_ms()
        self.conn.execute(
            """
            INSERT INTO brain_edges
                (id, source_id, target_id, relation_type, weight,
                 valid_at, invalid_at, expired_at, access_count,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, 1, ?, ?)
            """,
            (edge_id, source_id, target_id, relation_type, weight, now, now, now),
        )
        self.conn.commit()
        return edge_id

    def get_active_edges(self, source_id: str) -> List[Dict[str, Any]]:
        """Return all currently active (invalid_at IS NULL) edges from source_id."""
        rows = self.conn.execute(
            """
            SELECT * FROM brain_edges
            WHERE source_id = ? AND invalid_at IS NULL
            """,
            (source_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_edge_weight(self, source_id: str, target_id: str) -> float | None:
        """Return the current weight of the active edge source→target, or None."""
        row = self.conn.execute(
            "SELECT weight FROM brain_edges "
            "WHERE source_id = ? AND target_id = ? AND invalid_at IS NULL",
            (source_id, target_id),
        ).fetchone()
        return float(row["weight"]) if row else None

    def set_edge_weight(self, source_id: str, target_id: str, weight: float) -> None:
        """Set the weight of the active edge source→target, creating it if absent."""
        for nid in (source_id, target_id):
            if not self.conn.execute(
                "SELECT 1 FROM brain_nodes WHERE id = ?", (nid,)
            ).fetchone():
                self.upsert_node(nid, "concept", nid, "")
        existing = self.conn.execute(
            "SELECT id FROM brain_edges "
            "WHERE source_id = ? AND target_id = ? AND invalid_at IS NULL",
            (source_id, target_id),
        ).fetchone()
        if existing:
            self.update_edge_weight(existing["id"], weight)
        else:
            self.add_edge(source_id, target_id, "lateral", weight=weight)

    def update_edge_weight(self, edge_id: str, new_weight: float) -> None:
        """Update weight and updated_at for a specific edge."""
        self.conn.execute(
            "UPDATE brain_edges SET weight = ?, updated_at = ? WHERE id = ?",
            (new_weight, _now_ms(), edge_id),
        )
        self.conn.commit()

    def get_all_outgoing_weights(self, source_id: str) -> dict[str, float]:
        """Return {target_id: weight} for all active outgoing edges from source_id."""
        rows = self.conn.execute(
            "SELECT target_id, weight FROM brain_edges "
            "WHERE source_id = ? AND invalid_at IS NULL",
            (source_id,),
        ).fetchall()
        return {r["target_id"]: float(r["weight"]) for r in rows}

    def set_all_outgoing_weights(self, source_id: str, weights: dict[str, float]) -> None:
        """Replace all active outgoing edges from source_id with the given weights."""
        self.conn.execute(
            "UPDATE brain_edges SET invalid_at = strftime('%s','now')*1000 "
            "WHERE source_id = ? AND invalid_at IS NULL",
            (source_id,),
        )
        for tgt, w in weights.items():
            self.set_edge_weight(source_id, tgt, w)
        self.conn.commit()

    def get_outgoing_edges(self, source_id: str, min_weight: float = 0.0) -> list[dict]:
        """Return active outgoing edge dicts (target_id, weight, role, access_count)."""
        rows = self.conn.execute(
            "SELECT target_id, weight, relation_type AS role, access_count "
            "FROM brain_edges "
            "WHERE source_id = ? AND invalid_at IS NULL AND weight >= ?",
            (source_id, min_weight),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_edges(self) -> list[tuple[str, str, float]]:
        """Return all (source_id, target_id, weight) tuples for active edges."""
        rows = self.conn.execute(
            "SELECT source_id, target_id, weight FROM brain_edges "
            "WHERE invalid_at IS NULL"
        ).fetchall()
        return [(r["source_id"], r["target_id"], float(r["weight"])) for r in rows]

    # ------------------------------------------------------------------
    # Recursive CTE neighbour traversal
    # ------------------------------------------------------------------

    def neighbors(
        self,
        node_id: str,
        max_hops: int = 2,
        min_weight: float = 0.1,
    ) -> List[Dict[str, Any]]:
        """
        Return all reachable neighbour nodes within *max_hops* via active edges
        whose weight >= *min_weight*, excluding the seed node itself.

        Uses a recursive CTE for pure-SQL traversal (no Python BFS loop).
        """
        rows = self.conn.execute(
            """
            WITH RECURSIVE reach(node_id, depth) AS (
                -- seed
                SELECT ? AS node_id, 0 AS depth
                UNION
                -- expand one hop
                SELECT e.target_id, r.depth + 1
                FROM reach r
                JOIN brain_edges e
                    ON e.source_id = r.node_id
                   AND e.invalid_at IS NULL
                   AND e.weight >= ?
                WHERE r.depth < ?
            )
            SELECT DISTINCT n.*
            FROM reach r
            JOIN brain_nodes n ON n.id = r.node_id
            WHERE r.node_id != ?
            """,
            (node_id, min_weight, max_hops, node_id),
        ).fetchall()
        return [dict(r) for r in rows]
