"""
brain/sleep/consolidator.py
---------------------------
Nightly sleep consolidation worker — four phases:

  1. nrem_replay         — strengthen edges on replayed trajectories (×1.10)
  2. transitive_closure  — A→B ∧ B→C ⇒ A→C (composition)
  3. rem_abstract        — community abstraction into concept nodes
  4. shy_downscale       — multiplicative homeostasis w ← w · 0.95

Algorithm provenance (MIT / research ports — algorithm only, no GPL paste):
  - Track 2 sleep consolidation (architecture-fit + track-2-neuro-memory)
  - Transitive composition pattern: sss777999/Brain sleep_inference.py (MIT)
  - ExpeL distillation during REM abstraction (Apache-2.0 algorithm)
  - SHY multiplicative downscaling (Tononi & Cirelli), γ = 0.95
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

SHY_GAMMA = 0.95
REPLAY_LTP = 1.10
REPLAY_LTD = 0.98
TRANSITIVE_SCALE = 0.7
PRUNE_WEIGHT = 0.02


def _now_ms() -> int:
    return int(time.time() * 1000)


class SleepConsolidator:
    """
    Offline consolidator. Expects a GraphStore-like object with `.conn` and
    optional `add_edge` / `upsert_node` / `update_edge_weight` helpers.
    """

    def __init__(self, db: Any) -> None:
        self.db = db

    def run(
        self,
        replay_paths: Optional[Sequence[Sequence[str]]] = None,
        success_traces: Optional[Sequence[Dict[str, Any]]] = None,
        failure_traces: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        run_id = str(uuid.uuid4())
        paths = [list(p) for p in (replay_paths or [])]
        phases = [
            "nrem_replay",
            "transitive_closure",
            "rem_abstract",
            "shy_downscale",
        ]
        stats: Dict[str, Dict[str, int]] = {}

        # Phase 1 — NREM sharp-wave replay
        stats["nrem_replay"] = self._phase_replay(paths)
        self._log_phase(run_id, "nrem_replay", stats["nrem_replay"])

        # Phase 2 — transitive closure on replay seeds
        seeds: Set[str] = {n for path in paths for n in path}
        stats["transitive_closure"] = self._phase_transitive(seeds)
        self._log_phase(run_id, "transitive_closure", stats["transitive_closure"])

        # Phase 3 — REM community abstraction (+ optional ExpeL distill)
        stats["rem_abstract"] = self._phase_abstract(
            success_traces or [], failure_traces or []
        )
        self._log_phase(run_id, "rem_abstract", stats["rem_abstract"])

        # Phase 4 — SHY multiplicative downscale
        stats["shy_downscale"] = self._phase_downscale()
        self._log_phase(run_id, "shy_downscale", stats["shy_downscale"])

        return {
            "run_id": run_id,
            "phases_completed": phases,
            "stats": stats,
        }

    # ------------------------------------------------------------------
    # Phase 1: Replay strengthen
    # ------------------------------------------------------------------

    def _phase_replay(self, paths: Sequence[Sequence[str]]) -> Dict[str, int]:
        strengthened = 0
        weakened = 0
        replayed: Set[Tuple[str, str]] = set()
        for path in paths:
            for i in range(len(path) - 1):
                replayed.add((path[i], path[i + 1]))

        edges = self._active_edges()
        for e in edges:
            key = (e["source_id"], e["target_id"])
            w = float(e["weight"])
            if key in replayed:
                new_w = min(1.0, w * REPLAY_LTP)
                self._set_weight(e["id"], new_w)
                strengthened += 1
            else:
                # Mild LTD on non-replayed synapses sharing a replay endpoint
                endpoints = {n for pair in replayed for n in pair}
                if e["source_id"] in endpoints or e["target_id"] in endpoints:
                    new_w = w * REPLAY_LTD
                    self._set_weight(e["id"], new_w)
                    weakened += 1

        return {
            "nodes_processed": len({n for pair in replayed for n in pair}),
            "edges_strengthened": strengthened,
            "edges_pruned": 0,
            "lessons_added": 0,
            "skills_added": 0,
            "notes": f"ltp={strengthened},ltd={weakened}",
        }

    # ------------------------------------------------------------------
    # Phase 2: Transitive closure
    # ------------------------------------------------------------------

    def _phase_transitive(self, seed_ids: Set[str]) -> Dict[str, int]:
        """A→B ∧ B→C ⇒ A→C with w = w_AB * w_BC * 0.7 (port of sleep_inference)."""
        if not seed_ids:
            # Still useful to close over all intermediate nodes present
            seed_ids = {e["source_id"] for e in self._active_edges()} | {
                e["target_id"] for e in self._active_edges()
            }

        created = 0
        edges = self._active_edges()
        outgoing: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
        incoming: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
        existing: Set[Tuple[str, str]] = set()
        for e in edges:
            outgoing[e["source_id"]].append((e["target_id"], float(e["weight"])))
            incoming[e["target_id"]].append((e["source_id"], float(e["weight"])))
            existing.add((e["source_id"], e["target_id"]))

        for b in list(seed_ids):
            for a, w_ab in incoming.get(b, []):
                for c, w_bc in outgoing.get(b, []):
                    if a == c:
                        continue
                    if (a, c) in existing:
                        continue
                    w = max(0.01, min(1.0, w_ab * w_bc * TRANSITIVE_SCALE))
                    self._create_edge(a, c, "depends_on", w)
                    existing.add((a, c))
                    created += 1

        return {
            "nodes_processed": len(seed_ids),
            "edges_strengthened": created,
            "edges_pruned": 0,
            "lessons_added": 0,
            "skills_added": 0,
            "notes": f"transitive_edges_created={created}",
        }

    # ------------------------------------------------------------------
    # Phase 3: Community abstraction
    # ------------------------------------------------------------------

    def _phase_abstract(
        self,
        success_traces: Sequence[Dict[str, Any]],
        failure_traces: Sequence[Dict[str, Any]],
    ) -> Dict[str, int]:
        communities = self._detect_communities()
        concepts_made = 0
        for i, members in enumerate(communities):
            if len(members) < 2:
                continue
            concept_id = f"concept:{uuid.uuid4().hex[:12]}"
            label = f"community_{i}"
            if hasattr(self.db, "upsert_node"):
                self.db.upsert_node(
                    id=concept_id,
                    node_type="concept",
                    name=label,
                    content=f"REM abstraction over {sorted(members)}",
                )
            else:
                self._upsert_node_sql(
                    concept_id, "concept", label, f"REM abstraction over {sorted(members)}"
                )
            for m in members:
                # Weak abstraction link concept → member
                self._create_edge(concept_id, m, "defines", 0.3)
            concepts_made += 1

        lessons_added = 0
        if success_traces or failure_traces:
            try:
                from brain.reflect.distiller import LessonDistiller

                distiller = LessonDistiller(db=self.db)
                lessons = distiller.distill(
                    success_traces=success_traces,
                    failure_traces=failure_traces,
                )
                lessons_added = len(lessons)
            except Exception as exc:  # noqa: BLE001
                notes_extra = f"distill_error={type(exc).__name__}"
            else:
                notes_extra = f"lessons={lessons_added}"
        else:
            notes_extra = "no_traces"

        return {
            "nodes_processed": concepts_made,
            "edges_strengthened": 0,
            "edges_pruned": 0,
            "lessons_added": lessons_added,
            "skills_added": 0,
            "notes": f"communities={len(communities)},concepts={concepts_made},{notes_extra}",
        }

    def _detect_communities(self) -> List[Set[str]]:
        """Greedy modularity communities via networkx when available; else components."""
        edges = self._active_edges()
        nodes: Set[str] = set()
        edge_list: List[Tuple[str, str, float]] = []
        for e in edges:
            nodes.add(e["source_id"])
            nodes.add(e["target_id"])
            edge_list.append((e["source_id"], e["target_id"], float(e["weight"])))

        if not nodes:
            return []

        try:
            import networkx as nx
            from networkx.algorithms.community import greedy_modularity_communities

            g = nx.Graph()
            g.add_nodes_from(nodes)
            for u, v, w in edge_list:
                if g.has_edge(u, v):
                    g[u][v]["weight"] = max(g[u][v]["weight"], w)
                else:
                    g.add_edge(u, v, weight=w)
            return [set(c) for c in greedy_modularity_communities(g, weight="weight")]
        except Exception:
            # Fallback: undirected connected components
            adj: Dict[str, Set[str]] = defaultdict(set)
            for u, v, _ in edge_list:
                adj[u].add(v)
                adj[v].add(u)
            seen: Set[str] = set()
            comps: List[Set[str]] = []
            for n in nodes:
                if n in seen:
                    continue
                stack = [n]
                comp: Set[str] = set()
                while stack:
                    cur = stack.pop()
                    if cur in seen:
                        continue
                    seen.add(cur)
                    comp.add(cur)
                    stack.extend(adj[cur] - seen)
                comps.append(comp)
            return comps

    # ------------------------------------------------------------------
    # Phase 4: SHY downscale
    # ------------------------------------------------------------------

    def _phase_downscale(self) -> Dict[str, int]:
        pruned = 0
        processed = 0
        for e in self._active_edges():
            new_w = float(e["weight"]) * SHY_GAMMA
            if new_w < PRUNE_WEIGHT:
                self._invalidate_edge(e["id"])
                pruned += 1
            else:
                self._set_weight(e["id"], new_w)
            processed += 1
        return {
            "nodes_processed": processed,
            "edges_strengthened": 0,
            "edges_pruned": pruned,
            "lessons_added": 0,
            "skills_added": 0,
            "notes": f"gamma={SHY_GAMMA},pruned={pruned}",
        }

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _active_edges(self) -> List[Dict[str, Any]]:
        rows = self.db.conn.execute(
            "SELECT * FROM brain_edges WHERE invalid_at IS NULL"
        ).fetchall()
        return [dict(r) for r in rows]

    def _set_weight(self, edge_id: str, weight: float) -> None:
        if hasattr(self.db, "update_edge_weight"):
            self.db.update_edge_weight(edge_id, weight)
            return
        self.db.conn.execute(
            "UPDATE brain_edges SET weight = ?, updated_at = ? WHERE id = ?",
            (weight, _now_ms(), edge_id),
        )
        self.db.conn.commit()

    def _create_edge(
        self, source_id: str, target_id: str, relation_type: str, weight: float
    ) -> None:
        # Ensure endpoints exist (FK)
        for nid in (source_id, target_id):
            row = self.db.conn.execute(
                "SELECT id FROM brain_nodes WHERE id = ?", (nid,)
            ).fetchone()
            if row is None:
                self._upsert_node_sql(nid, "concept", nid, None)

        if hasattr(self.db, "add_edge"):
            self.db.add_edge(source_id, target_id, relation_type, weight=weight)
            return
        eid = str(uuid.uuid4())
        now = _now_ms()
        self.db.conn.execute(
            """
            INSERT INTO brain_edges
                (id, source_id, target_id, relation_type, weight,
                 valid_at, invalid_at, expired_at, access_count,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, 1, ?, ?)
            """,
            (eid, source_id, target_id, relation_type, weight, now, now, now),
        )
        self.db.conn.commit()

    def _upsert_node_sql(
        self, nid: str, node_type: str, name: str, content: Optional[str]
    ) -> None:
        now = _now_ms()
        self.db.conn.execute(
            """
            INSERT INTO brain_nodes
                (id, node_type, name, content, tags, last_accessed_at, created_at)
            VALUES (?, ?, ?, ?, '[]', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                content = excluded.content,
                last_accessed_at = excluded.last_accessed_at
            """,
            (nid, node_type, name, content, now, now),
        )
        self.db.conn.commit()

    def _invalidate_edge(self, edge_id: str) -> None:
        now = _now_ms()
        self.db.conn.execute(
            "UPDATE brain_edges SET invalid_at = ?, updated_at = ? WHERE id = ?",
            (now, now, edge_id),
        )
        self.db.conn.commit()

    def _log_phase(self, run_id: str, phase: str, stats: Dict[str, Any]) -> None:
        started = _now_ms()
        # Tiny synthetic duration so finished_at > started_at
        finished = started + 1
        self.db.conn.execute(
            """
            INSERT INTO sleep_log
                (run_id, started_at, finished_at, phase,
                 nodes_processed, edges_strengthened, edges_pruned,
                 lessons_added, skills_added, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{run_id}:{phase}",
                started,
                finished,
                phase,
                int(stats.get("nodes_processed", 0)),
                int(stats.get("edges_strengthened", 0)),
                int(stats.get("edges_pruned", 0)),
                int(stats.get("lessons_added", 0)),
                int(stats.get("skills_added", 0)),
                stats.get("notes"),
            ),
        )
        self.db.conn.commit()
