# Card B6: Fast Go Hook Shim & Watchdog Daemon

## Goal
Build `hookshim/` and `watchdog/` in Go. Compile a sub-5ms static binary `hookshim` called by Claude Code hooks to pass JSON to the brain daemon over Unix sockets with fail-open safety. Build `watchdog` to monitor health and schedule sleep jobs.

## Owned Paths
- `hookshim/`
- `watchdog/`
- `tests/hookshim/`

## Forbidden Paths
- `brain/`, `gateway/`, `studio/`, `contracts/`

## Inputs
- `contracts/hook-payloads.md`
- Shortlist Part 10: Claude Code CLI Native Hooks
- `research/errata.md` (Item 2)

## Acceptance Tests
1. `hookshim` executes in < 3.0ms on cold start.
2. If brain socket is unavailable or times out (>50ms), `hookshim` exits 0 with empty payload (fail-open).
3. If brain socket returns block decision, `hookshim` exits with code 2.
4. `watchdog` detects dead daemon and restarts process within 1s.

## Performance Budget
- Shim total execution time < 3.0ms.

## Deliverables
- `hookshim/main.go`
- `watchdog/main.go`
- `tests/hookshim/`

## Report Format
- At most 15 lines: cold-start latency measurements, fail-open behavior verified, watchdog loop tested.
