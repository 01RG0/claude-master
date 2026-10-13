"""Measure real performance against budgets (cross-platform rewrite)."""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from brain.store.graph import GraphStore
from brain.learning.hebbian import HebbianUpdater
from brain.learning.spreading import SpreadingActivation


def rss_mb():
    try:
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except ImportError:
        try:
            import psutil

            return psutil.Process().memory_info().rss / (1024 * 1024)
        except ImportError:
            return -1.0


class StoreAdapter:
    """Adapts GraphStore to the duck-typed interface HebbianUpdater expects."""

    def __init__(self, db):
        self.db = db

    def get_edge_weight(self, source_id, target_id):
        row = self.db.conn.execute(
            "SELECT weight FROM brain_edges WHERE source_id=? AND target_id=? AND invalid_at IS NULL",
            (source_id, target_id),
        ).fetchone()
        return float(row["weight"]) if row else None

    def set_edge_weight(self, source_id, target_id, weight):
        existing = self.db.conn.execute(
            "SELECT id FROM brain_edges WHERE source_id=? AND target_id=? AND invalid_at IS NULL",
            (source_id, target_id),
        ).fetchone()
        if existing:
            self.db.update_edge_weight(existing["id"], weight)
        else:
            self.db.add_edge(source_id, target_id, "lateral", weight=weight)

    def get_all_outgoing_weights(self, source_id):
        rows = self.db.conn.execute(
            "SELECT target_id, weight FROM brain_edges WHERE source_id=? AND invalid_at IS NULL",
            (source_id,),
        ).fetchall()
        return {r["target_id"]: float(r["weight"]) for r in rows}

    def set_all_outgoing_weights(self, source_id, weights):
        for tgt, w in weights.items():
            existing = self.db.conn.execute(
                "SELECT id FROM brain_edges WHERE source_id=? AND target_id=? AND invalid_at IS NULL",
                (source_id, tgt),
            ).fetchone()
            if existing:
                self.db.update_edge_weight(existing["id"], w)
            else:
                self.db.add_edge(source_id, tgt, "lateral", weight=w)

    def get_outgoing_edges(self, source_id, min_weight=0.0):
        rows = self.db.conn.execute(
            "SELECT target_id, weight, 'lateral' AS role, access_count "
            "FROM brain_edges WHERE source_id=? AND invalid_at IS NULL AND weight >= ?",
            (source_id, min_weight),
        ).fetchall()
        return [dict(r) for r in rows]


def bench():
    bench_db = os.path.join(tempfile.gettempdir(), "bench_claude_brain.db")
    try:
        os.remove(bench_db)
    except OSError:
        pass
    db = GraphStore(bench_db)
    db.upsert_node("n1", "concept", "a", "")
    db.upsert_node("n2", "concept", "b", "")
    db.upsert_node("n3", "concept", "c", "")
    db.add_edge("n1", "n2", "co_occurs", weight=0.5)
    db.add_edge("n2", "n3", "depends_on", weight=0.7)
    db.add_edge("n1", "n3", "depends_on", weight=0.3)

    rss = rss_mb()
    rss_str = f"{rss:.1f} MB" if rss >= 0 else "n/a (no resource/psutil)"
    print(f"=== Brain daemon RSS: {rss_str} (budget < 150 MB) ===")

    store = StoreAdapter(db)
    updater = HebbianUpdater()
    times = []
    for _ in range(300):
        t = time.perf_counter()
        updater.ltp(store, "n1", "n2", strength=0.8)
        times.append((time.perf_counter() - t) * 1000)
    times.sort()
    print(f"Hebbian update: p50={times[len(times)//2]:.2f}ms "
          f"p95={times[int(len(times)*.95)]:.2f}ms (budget < 5 ms)")

    sa = SpreadingActivation()
    times = []
    for _ in range(300):
        t = time.perf_counter()
        sa.activate(store, ["n1"], max_hops=2, min_weight=0.1, max_nodes=20)
        times.append((time.perf_counter() - t) * 1000)
    times.sort()
    print(f"Spreading retrieval: p50={times[len(times)//2]:.2f}ms "
          f"p95={times[int(len(times)*.95)]:.2f}ms")

    times = []
    for _ in range(300):
        t = time.perf_counter()
        db.conn.execute(
            "SELECT rule_text FROM lessons LIMIT 5",
        ).fetchall()
        times.append((time.perf_counter() - t) * 1000)
    times.sort()
    print(f"Prompt injection query (lessons): p50={times[len(times)//2]:.2f}ms "
          f"p95={times[int(len(times)*.95)]:.2f}ms (budget < 10 ms)")

    # Hook path end-to-end (in-process, no socket): stuck + gate + context
    from brain.server import BrainServer

    srv = BrainServer(bench_db, None, "127.0.0.1", 0)
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
               "session_id": "bench", "input": {"command": "git status"}}
    hook_times = []
    for _ in range(200):
        t = time.perf_counter()
        srv.handle_hook(dict(payload))
        hook_times.append((time.perf_counter() - t) * 1000)
    hook_times.sort()
    print(f"Hook handle_hook: p50={hook_times[len(hook_times)//2]:.2f}ms "
          f"p95={hook_times[int(len(hook_times)*.95)]:.2f}ms (budget < 10 ms)")

    db.close()
    try:
        srv.store.close()
    except Exception:
        pass
    try:
        os.remove(bench_db)
    except OSError:
        pass


if __name__ == "__main__":
    bench()
