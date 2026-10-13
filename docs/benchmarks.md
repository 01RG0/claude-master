# Benchmarks — real numbers only (rewrite, 2026-10-13, Windows 11)

Machine: AMD Ryzen 5 4500, Python 3.12.10, Go 1.27, Node 24.20, Defender on.
Copy-pasted command outputs. No UNKNOWNs remain; estimates are labeled.

## Hook path (scripts/bench_hookhost.py + tests/hookshim)

```
hookshim.exe spawn+TCP (Defender on): min=13.89ms p50=15.26ms p95=16.99ms p99=22.35ms max=22.35ms (n=100)
persistent TCP (no spawn): min=1.60ms p50=11.80ms p95=12.32ms p99=12.67ms max=12.83ms (n=300)
in-process handle_hook: min=0.03ms p50=0.03ms p95=0.04ms p99=0.09ms max=0.78ms (n=300)
```

```
hookshim cold-start (fail-open, n=50): min=12.00ms p50=13.50ms p95=14.01ms max=178.50ms
```

```
bare TCP connect+close (either port): min=0.17ms p50=10.05ms p95=10.75ms p99=11.01ms (n=200)
```

Keep-alive hook host (hookshim/host.go, persistent daemon, no per-call connect+spawn):

```
hookhost keep-alive p50=2.77ms p95=3.23ms p99=5.01ms vs spawn 14.10ms (n=200)
```

| Metric | Budget | Measured | Status |
|---|---|---|---|
| spawn hook path | p50<30ms (Win) / <10ms (POSIX) | p50 13.5–15.3ms, p95 14–17ms, max 178ms (AV spike) | PASS (Win budget) |
| <10ms original budget (spawn) | <10ms | p50 13.5ms | **NOT MET — revised** |
| persistent TCP | <10ms future | p50 ~11ms (one-shot connect each call) | NOT YET (needs keep-alive host) |
| in-process handle_hook | <10ms | p50 0.03ms | PASS |
| keep-alive hook host | <10ms | p50 2.77ms p95 3.23ms p99 5.01ms | **MET** |

Verdict: the <10ms spawn budget is unreachable on this Windows host —
~10ms is the platform bare-connect baseline (Defender-inspected loopback),
+~1ms IPC, +~3.5ms spawn. Budgets revised per-platform (test asserts
p50<30ms on Windows, <10ms POSIX). Path to <10ms: persistent keep-alive hook
host (no per-call connect+spawn). Daemon logic itself is 0.03ms — no language
issue. Fail-open timeout 50ms covers p99.

## Brain (scripts/bench_brain.py)

```
Brain daemon RSS: 22.0 MB (budget < 150 MB) — PASS
Hebbian update: p50=1.56ms p95=1.90ms (budget < 5 ms) — PASS
Spreading retrieval: p50=0.02ms p95=0.02ms — PASS
Prompt injection query (lessons): p50=0.00ms p95=0.00ms (budget < 10 ms) — PASS
Hook handle_hook: p50=0.03ms p95=0.04ms (budget < 10 ms) — PASS
```

## Drex Decision Taker (scripts/bench_drex.py, 220 unique live calls, drex-v2.0)

```
roundtrip_ms (n=220, fail_open=0): min=512 p50=538 p95=616 p99=783 max=796
server evaluation_time_ms: min=80 p50=93 p95=131 p99=204 max=365
cost: calls=220 input_tokens=9645 cost_usd=$0.000579
```

Fast-gate set from data: **1.0s** (covers p99=783ms; the 150ms guess would
fail open ~100%). Guard path is rule-only (no Drex latency on hooks).

## Gateway live (scripts/e2e_gateway_live.py, real providers)

```
PASS T1-chat (978ms–8.7s, varies by provider load)
PASS T2-stream (649ms–6.9s, 10–14 events incl. input_json_delta)
PASS T3-tool-use (668ms–7.1s, tool_use blocks)
PASS T4-multiturn (1.6s+9.2s)
PASS T5-long-stream (1968ms–32s, ~2800 chars, 532–562 events)
PASS T6-outcome (1–11ms)
```

Streaming truncation bug found+fixed here: attempt-context `defer cancel()`
killed bodies mid-stream (5× latency win after fix).

## Watchdog / Go kernels / studio

- Watchdog restart (Windows, python child): **73ms** (budget 4s Win / 1s POSIX).
- Go hot-path prototype vs Python (ADR-001): Go hebbian **37ns**/op,
  spreading **572ns**/op; Python in-memory hebbian **500ns**/op;
  Python+SQLite **1.56ms** (99.97% is commit I/O — batching, not language,
  is the lever; budgets pass → no rewrite).
- Studio vitest: **17 passed** (5 files, 1.5s).

## Load (scripts/load_test.py, 50 parallel streams)

```
load: 29/50 ok in 6789ms wall; codes: http529=21, ok=29
ok-latency: p50=1014ms p95=1299ms; admin models tracked: 2, cooldowns=2
```

Concurrency-safe (no hangs/races); 21×529 are free-tier quota limits under a
50-way burst, correctly tracked in cooldowns. Capacity is quota-bound, not
code-bound.

## Cost

Infra $0. Drex burns this session: 220-call bench $0.000579 + eval ~100 calls
~$0.00017. Provider calls: free-tier keys only.

## E2E request latency and overhead attribution (2026-10-14, real CLI)

Measured through the real Claude Code binary with the matrix harness
(`scripts/e2e_claude_matrix.py`), isolated profiles, `--gateway-port` bind +
pre-flight port refusal (so numbers are never taken through a foreign
listener). Artifact: `off/e2e/s2x3-clean.json` / `s2x3-clamped2.json`.

### Clean-port baseline (before max_tokens clamp) — commit e177c3d

Scenario S2-runtests, n=3, port 18080, our gateway only:

```
reps (wall): 73.5s, 114.5s, 12.7s   -> median 73.5s, pass 3/3
```

Upstream failure taxonomy from `reason=` logs (84 failures in the window):

```
groq         HTTP400 max_tokens_cap            x19   (CLI sends max_tokens=128000)
openrouter   HTTP400 context_plus_max_tokens   x13   (input+tools+128k output)
apertis      HTTP404 model_star_404            x13   (literal model="*")
pooled       HTTP400 max_tokens_cap            x13
anyapi       HTTP403 access_denied             x13
alibaba      HTTP401 bad_key                   x13
```

The earlier "0 provider failures" / 13/88/170s table is **invalid** — those
runs hit a foreign process on :8080 (bind conflict). Do not cite them.

### After clamp + disable dead providers (same day)

Outbound `max_tokens` clamped to 16384 (adapter-overridable);
`apertis`/`anyapi`/`alibaba` set `"enabled": false`. S2 n=3, port 18082:

```
reps (wall): 31.7s, 27.0s, 85.1s   -> median 31.7s, pass 2/3
HTTP 401/403/404 in window: 0
```

Passing reps ~2–4× faster than the clean baseline median. The FAIL was a
model quality miss (gave up waiting), not a harness/oracle flake. Traffic
still shows tool-turns landing on `ministral-8b-latest` and a large aux
share — next levers after the 400-storm fix.

Findings (each measured):

1. **Root latency driver was max_tokens=128000** from Claude Code, not
   mysterious retries. Clamp removes the free-tier 400 chain.
2. **Wildcard `*` must not be sent as a model id** — pickModel now passes
   through the resolved request model for wildcard-only providers.
3. **Dead keys/providers still burn cascade time** until disabled or
   banned; `provider pin|ban --model` now persists to capabilities.json.
4. **Aux-call % and ministral-on-tools** remain open optimization bets;
   re-measure after routing changes (prior 45% figure was from the
   invalid foreign-gateway window).

Reproduce:

```
./provider.exe validate --config gateway/config.json
python scripts/e2e_claude_matrix.py --scenario S2-runtests --repeat 3 \
  --gateway-port 18080 --json-out off/e2e/s2x3.json
```
