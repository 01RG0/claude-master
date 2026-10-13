# Audit (Phase 0) — rewrite branch, 2026-10-13

Baseline commit: `e0c712d` (main). Host: Windows 11, Python 3.12.10, Node v24.20.0,
no Go toolchain, no `.env` keys, `.venv/` Linux image committed to git.

## 1. What the README claims vs what exists

| Claimed (README) | Exists? | Verdict |
|---|---|---|
| `brain/` Python daemon (store, learning, guard, sleep, judge) | Yes, ~3.3k LOC, `brain/server.py` + 5 subpkgs | EXISTS, works in-process |
| `gateway/` Go Anthropic proxy, key pools, router | Yes, 9 `.go` files, stdlib-only | EXISTS, no `main` binary; `go` absent so uncompiled here |
| `hookshim/` Go static binary | Yes, `shim.go`+`main.go`, prebuilt ELF `hookshim` | EXISTS, ELF won't exec on Windows (`WinError 193`) |
| `watchdog/` Go health/restart/sleep | Yes, `watchdog.go`+`main.go` | EXISTS, logic correct but naive (no backoff) |
| `studio/` TS Sigma.js viewer | Yes, `src/` + 6 tests | EXISTS, `node_modules` absent so unrunnable here |
| `docs/` architecture/runbook/benchmarks | Yes, 9 md + cards + reviews + research (7 tracks) | EXISTS, stale/self-congratulatory |
| One-command bootstrap `./scripts/bootstrap.sh` + `make test` | `bootstrap.sh` Linux-only; `Makefile` assumes `.venv/bin/python`, `go`, `npm` | BROKEN on Windows |
| Budgets met (hook <10ms, learning <5ms, RSS <150MB, $0) | `docs/benchmarks.md` Linux snapshot | UNVERIFIED on this host (re-measured below) |

All five components exist structurally. Nothing is vaporware, but nothing runs
end-to-end on a fresh Windows clone.

## 2. Measured baseline (before rewrite, Windows)

```
python -m pytest -q
5 failed, 123 passed, 14 skipped, 9 errors in 6.12s
```

- `tests/brain`: 78 passed, 1 failed (`test_client_loads_key` — no `DREX_API_KEY`),
  1 skipped (live Drex, correctly skipped).
- `tests/security+chaos`: 40 passed, 12 skipped (Go probes, no toolchain),
  4 failed: 3× `test_daemon_down_shim_*` (ELF binary on Windows) + 1×
  `test_studio_mask_secret_runs_under_node` (node type-stripping).
- `tests/e2e`: 5 passed, 1 skipped, **9 errors** — all `daemon` fixture:
  `FileNotFoundError: /tmp/e2e_brain.log` (hardcoded Unix path on Windows).
- `studio`: 0 run (`node_modules` absent). `make test-go`: impossible (no `go`).

## 3. What works

- Store: WAL+FK+busy_timeout, authoritative `contracts/schema.sql`, FTS5 sync,
  bi-temporal `invalid_at IS NULL`, recursive-CTE `neighbors()`.
- Learning: exact Hebbian `η·R·a_pre·a_post·(W_MAX-w)` + clamp, FSRS formulas
  correct, spreading heap + refractory + role multipliers.
- Guard: 4-pattern stuck detector, precompiled safe/risky regex, socket server
  fail-safe `{allow:True}`, raw-stdlib fallback without `aiohttp`.
- Judge: safe→not-risky→Drex ordering, redacted `Tool/Category` only,
  `noul>0.85` block else fail-open, SHA256 TTL cache.
- Gateway (static review): correct SSE wire format, tool_use passthrough,
  key-pool cascade on 429, Thompson Beta bandit, privacy class routing.
- Hookshim fail-open, watchdog `<1s` restart (no backoff), studio ring/scrubber/pulse.

## 4. What is broken

1. **Windows paths (fatal):** `/tmp/...` hardcoded in `brain/server.py`,
   `socket_server.py`, `hookshim/shim.go`, `gateway/config.*`, README/runbook,
   `tests/e2e`, `scripts/bench_brain.py` (+`resource` import), `drex_decide.py`
   (`/home/rootuser/...`). `asyncio.start_unix_server` unsupported on Win32.
   `.venv` is a Linux image (`lib/`, no `Scripts/`); `Makefile` uses
   `.venv/bin/python`.
2. **Drex endpoint wrong:** code posts to `https://drex.nace.ai/v1/systemone`;
   docs say `https://console.nace.ai/v1/systemone`. Model hardcoded
   `drex-v1.5`; docs require `GET /v1/models` + `drex-latest`→`drex-v2.0`
   default. Timeouts 0.15–10s contradict docs-mandated ≥60s; no
   `retry-after-ms` honor, no circuit breaker, no cost accounting, key env
   name `DREX_API_KEY` vs docs `NACE_API_KEY`. `.env` parser ignores `export`,
   quotes, spaces.
3. **Gateway gaps:** no `package main` (README `./gateway` impossible),
   `config.go` JSON-only but README says `--config gateway/config.toml`,
   `CEREASRAS_API_KEY` typo, `hookshim/`+`watchdog/` have no `go.mod`
   (`make test-go` fails), text-only SSE (tool deltas dropped), no
   `Retry-After` honor, cooldown in-memory only.
4. **Dead code / drift:** `server.py:84 if False`, per-hook `StuckDetector()`
   alloc, `_build_context` does `tags LIKE '%lesson%'` (never hits `lessons`
   table/FTS/skills/spreading), `record_outcome` drops `latency_ms`, decisions
   logged to markdown only (never `decisions` table), FSRS never called,
   `fastapi/uvicorn/websockets/httpx/networkx` in deps but unused-or-missing.
5. **Repo hygiene:** `.venv/` (2.9k files) committed, `.gitignore` missing
   `.venv/*.db/*.sock`, no `.env.example`, no secret scan, CI workflow deleted.

## 5. What is missing (vs mission)

- Decision Taker clean interface (gateway/guard/judge/learning/sleep/watchdog
  call sites), dynamic model resolution, retries/circuit-breaker/cost caps,
  JSONL decision log, threshold calibration set.
- Cross-platform bootstrap/run (`bootstrap.py`, `bootstrap.sh` fix, one start cmd).
- Gateway binary entrypoint, `hookshim`/`watchdog` modules, TOML/JSON convergence.
- Real-API integration evidence (no keys provided; live tests skip by design).
- Honest `docs/test-report.md` + re-measured `docs/benchmarks.md` on this host.

## 6. Rewrite direction (summary)

Keep Python-brain + Go-gateway/shim/dog + TS-studio (numbers justify it — §7 of
mission, measured below). Fix paths, Drex transport, gateway binary/modules,
hygiene, docs. No Rust: no toolchain, no budget breach to justify a third
language. Details in `docs/decisions.md` (ADR-001..006).
