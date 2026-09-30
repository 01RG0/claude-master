# WebSocket Events Contract

Version: 0.1.0 — frozen after Wave 0

The brain daemon exposes a WebSocket endpoint at `ws://localhost:7700/ws`.
The studio connects here and receives real-time events as JSON-encoded
messages. The studio must never write back to the DB; it is read-only.

---

## Connection

```
GET ws://localhost:7700/ws
```

Optional query parameters:
- `session_id`: filter events to a specific Claude Code session
- `since_ts`: Unix epoch; replay all events after this timestamp

On connection the server immediately sends a `snapshot` event containing
the full current graph state.

---

## Envelope

Every message from server → client is a JSON object with this envelope:

```json
{
  "event": "<event_name>",
  "ts":    <unix_epoch_ms>,
  "data":  { ... }
}
```

---

## Event Catalogue

### `snapshot`
Full initial graph state sent once on connection.
```json
{
  "event": "snapshot",
  "ts": 1727739123000,
  "data": {
    "nodes": [ { "id": "...", "name": "...", "node_type": "...", "weight_sum": 2.3 } ],
    "edges": [ { "id": "...", "source": "...", "target": "...", "weight": 0.72, "relation_type": "causes" } ],
    "sleep_phase": null
  }
}
```

### `node_fired`
A brain node was activated during spreading activation.
```json
{
  "event": "node_fired",
  "ts": 1727739124500,
  "data": {
    "node_id": "uuid-abc",
    "activation_score": 0.83,
    "session_id": "sess-xyz"
  }
}
```

### `synapse_updated`
A synaptic edge weight changed after a Hebbian update.
```json
{
  "event": "synapse_updated",
  "ts": 1727739126000,
  "data": {
    "edge_id": "uuid-def",
    "source_id": "uuid-abc",
    "target_id": "uuid-ghi",
    "old_weight": 0.45,
    "new_weight": 0.61,
    "delta": 0.16,
    "reward": 1.0
  }
}
```

### `edge_invalidated`
A bi-temporal edge was superseded by a contradicting fact.
```json
{
  "event": "edge_invalidated",
  "ts": 1727739127000,
  "data": {
    "edge_id": "uuid-old",
    "replacement_edge_id": "uuid-new"
  }
}
```

### `circuit_breaker_tripped`
The stuck detector halted an action loop.
```json
{
  "event": "circuit_breaker_tripped",
  "ts": 1727739128000,
  "data": {
    "session_id": "sess-xyz",
    "pattern": "repeating_action_error",
    "iteration": 3,
    "nudge_generated": true
  }
}
```

### `sleep_phase`
Nightly sleep job phase started/completed.
```json
{
  "event": "sleep_phase",
  "ts": 1727739200000,
  "data": {
    "run_id": "sleep-uuid",
    "phase": "nrem_replay",       // nrem_replay | transitive_closure | rem_abstract | shy_downscale
    "state": "started",           // started | completed
    "edges_strengthened": 142,
    "edges_pruned": 17,
    "lessons_added": 3
  }
}
```

### `skill_learned`
A new skill was saved to the procedural skill store.
```json
{
  "event": "skill_learned",
  "ts": 1727739210000,
  "data": {
    "skill_id": "skill-uuid",
    "name": "run_migrations",
    "version": 1,
    "language": "python"
  }
}
```

### `lesson_extracted`
A new operational rule was distilled from trajectory pairs.
```json
{
  "event": "lesson_extracted",
  "ts": 1727739211000,
  "data": {
    "lesson_id": "lesson-uuid",
    "rule_text": "Always run go fmt before submitting",
    "confidence": 0.91
  }
}
```

### `gateway_health`
Gateway health and key status update, emitted every 10 seconds.
```json
{
  "event": "gateway_health",
  "ts": 1727739220000,
  "data": {
    "providers": [
      { "name": "groq", "active_keys": 2, "cooldown_keys": 0 },
      { "name": "cerebras", "active_keys": 1, "cooldown_keys": 1 }
    ],
    "requests_last_60s": 12
  }
}
```

### `replay_frame`
Emitted during time-scrubber replay at the timestamp position.
```json
{
  "event": "replay_frame",
  "ts": 1727739230000,
  "data": {
    "replay_ts": 1727700000000,
    "active_node_ids": ["uuid-abc", "uuid-xyz"],
    "active_edge_ids": ["uuid-def"]
  }
}
```

---

## Client → Server Messages

Only two messages are accepted from the client:

### `subscribe`
```json
{ "action": "subscribe", "session_id": "sess-xyz" }
```

### `replay`
```json
{ "action": "replay", "from_ts": 1727700000000, "to_ts": 1727739230000, "speed": 2.0 }
```
