# Card C0: Shared Contracts & Interface Definitions

## Goal
Define and freeze the foundational data contracts across Python, Go, and TypeScript. Refine the SQLite schema, WebSocket event schemas, OpenAPI specifications, and Gateway configuration schemas so all subsequent builder cards can implement against concrete, immutable interfaces.

## Owned Paths
- `contracts/schema.sql`
- `contracts/brain.openapi.yaml`
- `contracts/events.md`
- `contracts/gateway-config.schema.json`

## Forbidden Paths
- All files outside `contracts/`

## Inputs
- `research/architecture-fit.md` (Section 4 SQLite schema)
- `research/track-1-memory.md` (bi-temporal edge definitions)
- `research/track-3-routers.md` (gateway configuration models)
- `research/track-7-graph-viz.md` (synaptic event types)

## Acceptance Tests
1. `contracts/schema.sql` parses cleanly in SQLite with all foreign keys and virtual tables (`vec0`, `fts5`).
2. Schema includes: `brain_nodes`, `brain_edges`, `brain_node_vectors`, `episodic_events`, `model_stats`, `key_state`, `request_log`, `lessons`, `skills`, `sleep_log`, `decisions`.
3. `contracts/brain.openapi.yaml` validates against OpenAPI 3.0 specification.
4. `contracts/gateway-config.schema.json` validates against JSON Schema Draft-07.

## Performance Budget
- Schema definitions must support sub-5ms indexed lookups on a 100,000 edge graph.

## Deliverables
- `contracts/schema.sql`
- `contracts/brain.openapi.yaml`
- `contracts/events.md`
- `contracts/gateway-config.schema.json`

## Report Format
- At most 15 lines: contracts created, validation results, open issues, version tag.
