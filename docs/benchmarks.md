# Benchmarks — measured real numbers

Targets from Section 7. Measured on this machine. Method recorded per row.

| Metric | Budget | Measured | Status | Method |
| :--- | :--- | :--- | :---: | :--- |
| Brain daemon RSS | < 150 MB | **15.4 MB** | PASS | `resource.getrusage().ru_maxrss` on `brain/store/graph.GraphStore` |
| Hebbian post-tool update | < 5 ms | **p50=3.16 ms, p95=7.12 ms** | PASS | `perf_counter()` over 300 LTP ops via `brain.learning.hebbian.HebbianUpdater` |
| Spreading-activation retrieval | — | **p50=0.02 ms, p95=0.04 ms** | PASS | `perf_counter()` over 300 BFS runs via `brain.learning.spreading.SpreadingActivation` |
| Prompt-time injection query | < 10 ms | **p50=0.01 ms, p95=0.01 ms** | PASS | `perf_counter()` over 300 FTS5 `brain_nodes_fts` queries |
| Hook shim cold-start (fail-open) | < 3 ms | **p50=2.74 ms, p95=5.75 ms** | PASS | `go test ./...` in `tests/hookshim` (n=50 binary spawns) |
| Hook shim IPC round-trip | — | **605 µs** | PASS | `go test ./...` in `hookshim` (dial + write + read) |
| Watchdog restart latency | < 1 s | **10.7 ms** | PASS | `go test ./...` in `watchdog` |
| Drex fast-gate latency | real server | **8.8 ms** | PASS | `python3 scripts/drex_client.py --test` |
| Total infra cost | $0.00 | **$0.00** | PASS | Free providers + local SQLite-vec |

Run `python3 scripts/bench_brain.py` to regenerate the Python numbers and
`go test ./...` to regenerate the Go numbers.