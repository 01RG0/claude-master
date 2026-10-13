# Benchmarks — measured real numbers (rewrite, 2026-10-13, Windows)

Host: Windows 11, Python 3.12.10, `python scripts/bench_brain.py` (cross-platform
rewrite; `resource` replaced by `psutil` fallback). Copy-pasted output:

```
=== Brain daemon RSS: 21.4 MB (budget < 150 MB) ===
Hebbian update: p50=1.54ms p95=1.77ms (budget < 5 ms)
Spreading retrieval: p50=0.02ms p95=0.02ms
Prompt injection query (lessons): p50=0.00ms p95=0.00ms (budget < 10 ms)
Hook handle_hook: p50=0.03ms p95=0.05ms (budget < 10 ms)
```

| Metric | Budget | Measured (this host) | Status | Method |
|---|---|---|---|---|
| Brain daemon RSS | < 150 MB | 21.4 MB | PASS | `psutil.Process().memory_info()` in `scripts/bench_brain.py` |
| Hebbian post-tool update | < 5 ms | p50=1.54ms p95=1.77ms | PASS | `perf_counter` 300× `HebbianUpdater.ltp` |
| Spreading-activation retrieval | — | p50=0.02ms p95=0.02ms | PASS | `perf_counter` 300× `SpreadingActivation.activate` |
| Prompt-time injection query (lessons) | < 10 ms | p50=0.00ms p95=0.00ms | PASS | `perf_counter` 300× `SELECT rule_text FROM lessons` (+FTS when query non-empty) |
| Hook `handle_hook` end-to-end (in-process) | < 10 ms | p50=0.03ms p95=0.05ms | PASS | `perf_counter` 200× `BrainServer.handle_hook(git status)` |
| Hook shim cold-start / IPC | < 10 ms | not re-measured here (no Go toolchain) | UNKNOWN | prior Linux: cold-start p50 2.74ms, IPC 605us |
| Watchdog restart | < 1 s | not re-measured here | UNKNOWN | prior Linux: 10.7ms |
| Drex fast-gate | real server | not measured (no key; live tests skip) | SKIP | `TestDrexClient::test_drex_live_call` skipped by design |
| Total infra cost | $0.00 (+ Drex usage) | $0.00 (0 Drex calls this run) | PASS | free providers + local SQLite; `DrexClient.cost_summary()` tracks spend |

Notes:
- Prior Linux snapshot (`docs/benchmarks.md` pre-rewrite) reported RSS 15.4 MB,
  Hebbian p50 3.16ms, spreading 0.02ms, injection 0.01ms, shim 2.74ms,
  watchdog 10.7ms, Drex 8.8ms. Windows numbers are same-order or better; the
  `_build_context` change (lessons table + FTS instead of `tags LIKE`) removed
  the only full-scan query on the hook path.
- `sqlite-vec` unavailable in this env (`sqlite-vec extension not available`,
  graceful degradation); vector KNN remains unmeasured by design.
- Regenerate: `python scripts/bench_brain.py`. Go numbers: `cd gateway &&
  go test ./...` (requires Go toolchain; absent on this host).
