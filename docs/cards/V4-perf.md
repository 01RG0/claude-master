# Card V4: Real Server Performance & Budget Measurements

## Goal
Measure and record actual performance numbers on the real server for all Section 7 budgets. Populate `docs/benchmarks.md`.

## Owned Paths
- `docs/benchmarks.md`
- `scripts/benchmark_runner.py`

## Acceptance Tests
1. Prompt-time injection latency measured on real SQLite database.
2. Hook shim execution overhead measured via time-tracer.
3. Brain daemon and Go gateway memory measured under load.
