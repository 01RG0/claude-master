# Card B8: Drex Decision Client & Runtime Gating Policy

## Goal
Build `brain/judge`. Integrate the modernized Drex decision client into the brain runtime. Implement pre-execution safety gating, command syntax sanity checks, in-memory decision caching, and fail-open timeout management.

## Owned Paths
- `brain/judge/`
- `tests/brain/test_judge.py`

## Forbidden Paths
- `gateway/`, `hookshim/`, `studio/`, `contracts/`

## Inputs
- `scripts/drex_client.py`
- Shortlist Part 7: Drex System-1 (`POST /v1/systemone`)
- `research/errata.md` (Item 3)

## Acceptance Tests
1. Gating policy classifies dangerous bash commands (e.g. `rm -rf /`, credentials exfiltration) as rejected.
2. Gating policy classifies standard development tools (`git status`, `go test`, `pytest`) as approved.
3. Cache returns identical queries in < 0.2ms without network calls.
4. Any network error or timeout (>150ms) triggers fail-open approval with warning logged.

## Performance Budget
- Cache hit latency < 0.2ms.
- Timeout limit hard-capped at 150ms.

## Deliverables
- `brain/judge/client.py`
- `brain/judge/gating.py`
- `brain/judge/cache.py`
- `tests/brain/test_judge.py`

## Report Format
- At most 15 lines: safety classification accuracy, cache hit latency, fail-open verification.
