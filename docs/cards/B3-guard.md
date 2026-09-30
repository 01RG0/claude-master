# Card B3: Deterministic Loop Guard & Socket Server

## Goal
Build `brain/guard`. Implement OpenHands 5-pattern stuck detector, working-memory context injection builder, and the non-blocking local Unix domain socket IPC listener.

## Owned Paths
- `brain/guard/`
- `tests/brain/test_guard.py`

## Forbidden Paths
- `gateway/`, `hookshim/`, `studio/`, `contracts/`

## Inputs
- `contracts/schema.sql`
- `contracts/hook-payloads.md`
- Shortlist Part 1: `OpenHands/software-agent-sdk` (`stuck_detector.py`)

## Acceptance Tests
1. Stuck detector catches 4 repeating identical action-observations and trips circuit breaker.
2. Stuck detector catches alternating ping-pong cycles ($A 	o B 	o A 	o B$).
3. Structural normalizer (`_event_eq`) ignores ephemeral UUIDs and timestamps.
4. Socket server processes hook requests and responds with context injection within 4ms.

## Performance Budget
- Hook socket response latency < 4.0ms end-to-end.
- Event normalizer < 0.5ms per check.

## Deliverables
- `brain/guard/stuck_detector.py`
- `brain/guard/context_builder.py`
- `brain/guard/socket_server.py`
- `tests/brain/test_guard.py`

## Report Format
- At most 15 lines: loop patterns tested, socket IPC latency, circuit breaker behavior.
