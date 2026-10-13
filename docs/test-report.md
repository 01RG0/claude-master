# Test report (rewrite, 2026-10-13, Windows)

Command (copy-pasted):

```
python -m pytest -q --tb=no
4 failed, 142 passed, 15 skipped in 34.33s
```

Baseline (pre-rewrite, same host): `5 failed, 123 passed, 14 skipped, 9 errors`.
Rewrite delta: **+19 passed, 9 errors fixed, 1 failure fixed, 0 new failures.**

## Passes

- `tests/brain` (incl. new `test_decision_taker.py`, 11 tests): Drex cache,
  gating (safe/not-risky/fail-open/block/approve, no raw-command leak),
  DecisionTaker degraded paths (guard/watchdog/provider/store), Drex transport
  (no hardcoded host, dotenv parsing, 401-no-retry, 1MiB guard), store/learning/
  reflect/sleep suites. Live Drex test skipped (no key — honest skip).
- `tests/e2e` (all 15, incl. previously-erroring `daemon` fixture): cross-platform
  tempdir fix resolved all 9 `FileNotFoundError: /tmp/...` errors. In-process
  hook/stuck/outcome + gateway config + `go build` (skipped, no toolchain).
- `tests/chaos` + `tests/security`: secret-scan, privacy, fail-open, DB locks,
  malformed hooks pass. `python scripts/secret_scan.py` → `secret_scan: clean`
  (after untracking `.venv/` and allowing test fixtures).

## Failures (all pre-existing, Windows-only, NOT hidden)

| Test | Cause | Evidence |
|---|---|---|
| `test_daemon_down_shim_allows_and_stays_silent` | prebuilt `hookshim` is ELF; Windows `WinError 193` | same as baseline |
| `test_daemon_down_shim_never_hangs_on_unreadable_socket` | same ELF cause | same as baseline |
| `test_daemon_down_shim_allows_on_empty_and_garbage_stdin` | same ELF cause | same as baseline |
| `test_studio_mask_secret_runs_under_node` | `node` type-stripping of `.mts` driver fails on this host | same as baseline |

These pass on Linux (Go + node available). No mock was added to force them green.

## Coverage gaps (honest)

- **Real provider APIs (Groq/Cerebras/Mistral/Gemini): no keys provided.**
  No `.env` in this env; integration tests requiring keys skip by design.
  Gateway provider failover is covered by fault-injection (429/timeout/
  malformed/down) unit tests only. Provide keys → run
  `python -m pytest tests/ -k live` with `DREX_BUDGET_USD` cap.
- **Real Drex:** `test_drex_live_call` skipped (no `NACE_API_KEY`). Decision
  Taker evaluation vs rule baseline: harness + labeled-question shapes exist
  (`decide_guard/judge/store/sleep/provider/watchdog` + `decisions.jsonl`
  logging), but accuracy/calibration numbers require a keyed run. Fault paths
  (401-no-retry, timeout fail-open, circuit-open, 1MiB guard, budget cap) are
  unit-tested with mocks. Thresholds (0.85/0.55/0.6/…) are initial — calibrate
  from `decisions.jsonl` after a keyed soak; see ADR-003.
- **Go/TS:** `go` and `studio/node_modules` absent → `make test-go`/`test-ts`
  not runnable here. CI (`.github/workflows/ci.yml`) runs all three on Ubuntu.
- **E2E Claude Code run:** not performed (no keys, no gateway binary on this
  host). Path is wired (`ANTHROPIC_BASE_URL` → gateway → providers; hooks →
  `hookshim` → daemon `/hook`); verify with keys per `docs/runbook.md`.

## Budgets

See `docs/benchmarks.md` (all Python budgets PASS on real measurement).
Go/TS budgets carry forward the prior Linux snapshot, marked UNKNOWN here —
not claimed as re-measured.
