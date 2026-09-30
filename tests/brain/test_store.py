"""
tests/brain/test_store.py
B1 Brain Store acceptance tests — written BEFORE implementation.
Run: python3 -m pytest tests/brain/test_store.py -v
"""

import time
import sqlite3
import tempfile
import os
import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_brain.db")


@pytest.fixture
def brain_db(db_path):
    from brain.store.db import BrainDB
    db = BrainDB(db_path)
    yield db
    db.close()


@pytest.fixture
def graph_store(db_path):
    from brain.store.graph import GraphStore
    gs = GraphStore(db_path)
    yield gs
    gs.close()


@pytest.fixture
def temporal_store(db_path):
    from brain.store.temporal import TemporalStore
    ts = TemporalStore(db_path)
    yield ts
    ts.close()


# ---------------------------------------------------------------------------
# Test 1: DB creates all tables
# ---------------------------------------------------------------------------

def test_db_creates_all_tables(brain_db):
    """Schema SQL must create all 11 expected tables (virtual tables included)."""
    conn = brain_db.conn
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'shadow') "
        "UNION SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    table_names = {r[0] for r in rows}

    expected_tables = {
        "brain_nodes",
        "brain_nodes_fts",
        "brain_edges",
        "episodic_events",
        "model_stats",
        "key_state",
        "request_log",
        "lessons",
        "lessons_fts",
        "skills",
        "skills_fts",
        "sleep_log",
        "decisions",
    }
    missing = expected_tables - table_names
    assert not missing, f"Missing tables: {missing}"


# ---------------------------------------------------------------------------
# Test 2: upsert_node round-trip
# ---------------------------------------------------------------------------

def test_upsert_node(graph_store):
    """upsert_node returns a dict; get_node retrieves with correct fields."""
    node = graph_store.upsert_node(
        id="node-001",
        node_type="concept",
        name="SQLite Brain",
        content="Local embedded database",
        tags=["db", "storage"],
    )
    assert node["id"] == "node-001"
    assert node["node_type"] == "concept"
    assert node["name"] == "SQLite Brain"

    fetched = graph_store.get_node("node-001")
    assert fetched is not None
    assert fetched["id"] == "node-001"
    assert fetched["name"] == "SQLite Brain"
    assert fetched["content"] == "Local embedded database"

    # upsert again (update)
    graph_store.upsert_node(
        id="node-001",
        node_type="concept",
        name="SQLite Brain v2",
        content="Updated content",
    )
    updated = graph_store.get_node("node-001")
    assert updated["name"] == "SQLite Brain v2"


# ---------------------------------------------------------------------------
# Test 3: add_edge and get_active_edges
# ---------------------------------------------------------------------------

def test_add_and_get_edge(graph_store):
    """Adding two nodes and an edge; get_active_edges returns it."""
    graph_store.upsert_node(id="src", node_type="file", name="Source")
    graph_store.upsert_node(id="tgt", node_type="file", name="Target")

    edge_id = graph_store.add_edge(
        source_id="src",
        target_id="tgt",
        relation_type="depends_on",
        weight=0.8,
    )
    assert isinstance(edge_id, str) and len(edge_id) > 0

    edges = graph_store.get_active_edges("src")
    assert len(edges) == 1
    assert edges[0]["target_id"] == "tgt"
    assert edges[0]["relation_type"] == "depends_on"
    assert abs(edges[0]["weight"] - 0.8) < 1e-6


# ---------------------------------------------------------------------------
# Test 4: bi-temporal contradiction resolution
# ---------------------------------------------------------------------------

def test_bi_temporal_contradiction(temporal_store):
    """
    Adding a fact then a contradicting fact must:
    - Set invalid_at on the original edge (not delete it)
    - Create a new active edge
    """
    temporal_store.upsert_node(id="A", node_type="concept", name="NodeA")
    temporal_store.upsert_node(id="B", node_type="concept", name="NodeB")

    old_edge_id = temporal_store.add_fact("A", "B", "causes", weight=0.5)
    # Small sleep so timestamps differ
    time.sleep(0.01)
    new_edge_id = temporal_store.add_fact("A", "B", "causes", weight=0.9)

    # old_edge must now have invalid_at set
    conn = temporal_store.conn
    old_row = conn.execute(
        "SELECT invalid_at FROM brain_edges WHERE id = ?", (old_edge_id,)
    ).fetchone()
    assert old_row is not None, "Old edge should still exist (non-destructive)"
    assert old_row[0] is not None, "Old edge invalid_at must be set"

    # new_edge must be active
    new_row = conn.execute(
        "SELECT invalid_at, weight FROM brain_edges WHERE id = ?", (new_edge_id,)
    ).fetchone()
    assert new_row is not None
    assert new_row[0] is None, "New edge invalid_at must be NULL (active)"
    assert abs(new_row[1] - 0.9) < 1e-6


# ---------------------------------------------------------------------------
# Test 5: recursive neighbors (3-node chain)
# ---------------------------------------------------------------------------

def test_recursive_neighbors(graph_store):
    """A->B->C; neighbors(A, max_hops=2) must return B and C."""
    graph_store.upsert_node(id="nA", node_type="concept", name="Alpha")
    graph_store.upsert_node(id="nB", node_type="concept", name="Beta")
    graph_store.upsert_node(id="nC", node_type="concept", name="Gamma")

    graph_store.add_edge("nA", "nB", "reinforces", weight=0.7)
    graph_store.add_edge("nB", "nC", "reinforces", weight=0.6)

    neighbors = graph_store.neighbors("nA", max_hops=2, min_weight=0.1)
    neighbor_ids = {n["id"] for n in neighbors}
    assert "nB" in neighbor_ids, "Direct neighbor B must be present"
    assert "nC" in neighbor_ids, "2-hop neighbor C must be present"
    # A itself should not appear
    assert "nA" not in neighbor_ids


# ---------------------------------------------------------------------------
# Test 6: FTS5 full-text search
# ---------------------------------------------------------------------------

def test_fts_search(graph_store):
    """Node inserted with specific content must be retrievable via FTS query."""
    graph_store.upsert_node(
        id="fts-node",
        node_type="rule",
        name="Mutex Deadlock Prevention",
        content="Always release the mutex before returning from the function",
    )

    conn = graph_store.conn
    rows = conn.execute(
        "SELECT id FROM brain_nodes_fts WHERE brain_nodes_fts MATCH ?",
        ("mutex",),
    ).fetchall()
    ids = [r[0] for r in rows]
    assert "fts-node" in ids, "FTS must find the node by 'mutex' keyword"

    rows2 = conn.execute(
        "SELECT id FROM brain_nodes_fts WHERE brain_nodes_fts MATCH ?",
        ("deadlock",),
    ).fetchall()
    ids2 = [r[0] for r in rows2]
    assert "fts-node" in ids2, "FTS must find the node by 'deadlock' keyword"
