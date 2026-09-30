# Card V1: Multi-Language Contract & Schema Validation

## Goal
Independent verification of contract compliance across Python, Go, and TypeScript. Ensure database schemas, WebSocket event envelopes, and API payloads match `contracts/` exactly.

## Owned Paths
- `tests/verification/test_contracts.py`
- `tests/verification/contracts_test.go`

## Forbidden Paths
- `brain/`, `gateway/`, `hookshim/`, `studio/`, `contracts/`

## Inputs
- `contracts/` specifications

## Acceptance Tests
1. Python store models exactly match `contracts/schema.sql`.
2. Go gateway structures serialize to exact `contracts/gateway-config.schema.json`.
3. WebSocket event payloads match `contracts/events.md`.

## Deliverables
- `tests/verification/test_contracts.py`
- `tests/verification/contracts_test.go`
