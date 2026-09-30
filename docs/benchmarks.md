# System Benchmark & Latency Targets

*Record of real measured performance against Section 7 budgets.*

---

## 1. Budget Targets vs Real Measured Latencies

| Subsystem / Metric | Budget Target | Measured Latency | Measured Memory | Status | Measurement Method / Command |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **Hook Prompt Injection** | < 10.0 ms | *Pending Wave 1* | - | QUEUED | In-process daemon BFS query over SQLite cache |
| **Hook Shim Overhead** | < 3.0 ms | *Pending Wave 1* | - | QUEUED | Static Go binary startup + Unix socket echo |
| **Post-Tool Learning Update** | < 5.0 ms | *Pending Wave 1* | - | QUEUED | SQLite update + Hebbian weight calculation |
| **Brain Daemon Memory** | < 150.0 MB | *Pending Wave 1* | - | QUEUED | RSS via `ps aux` / memory profiler |
| **Go Gateway Memory** | Minimal (< 30 MB) | *Pending Wave 1* | - | QUEUED | Go runtime runtime.MemStats / RSS |
| **Drex Fast Gating** | Real server call | **8.8 ms** (req) | - | **PASS** | `python3 scripts/drex_client.py --test` |
| **Total Cloud Infra Cost** | $0.00 / month | **$0.00** | - | **PASS** | Embedded SQLite-vec + Free Provider Tiers |
