# Card B1: Brain Store & SQLite-Vec Hybrid Engine

## Goal
Build the core storage subsystem in `brain/store`. Implement SQLite database management with dynamic `sqlite-vec` extension loading, full-text FTS5 search, bi-temporal edge tracking (`valid_at`, `invalid_at`), and non-destructive contradiction resolution.

## Owned Paths
- `brain/store/`
- `tests/brain/test_store.py`

## Forbidden Paths
- `gateway/`, `hookshim/`, `studio/`, `contracts/`

## Inputs
- `contracts/schema.sql`
- Shortlist Part 2: `getzep/graphiti` (`edges.py`, `edge_operations.py`)
- Shortlist Part 3: `asg017/sqlite-vec` (`sqlite-vec.c`)

## Acceptance Tests
1. Database initializes with all tables from `contracts/schema.sql`.
2. `sqlite-vec` loads successfully; cosine similarity search on 384-dim embeddings returns expected ranking.
3. Adding a contradicting fact invalidates the previous edge timestamp without deleting historical row.
4. Recursive CTE graph traversal returns connected neighbors up to depth 3 within 2ms.

## Performance Budget
- Vector similarity search (top-5) < 3.0ms on 10k vectors.
- Edge traversal < 2.0ms.

## Deliverables
- `brain/store/db.py`
- `brain/store/graph.py`
- `brain/store/temporal.py`
- `tests/brain/test_store.py`

## Report Format
- At most 15 lines: modules built, test coverage, vector & graph latency results, schema conformance.
