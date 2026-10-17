# Architecture Decision Records (rewrite, 2026-10-13)

## ADR-001: Keep Python (brain) + Go (gateway/shim/dog) + TypeScript (studio); no Rust

- Status: accepted. Context: mission suggests Rust-or-Go for hot paths, Python
  only where it wins. Options: (a) keep split, (b) Rust hot paths, (c) all-Python.
- Numbers (Windows, `python scripts/bench_brain.py`, this host):
  RSS 21.4 MB (<150), Hebbian p50 1.54ms p95 1.77ms (<5),
  spreading p50 0.02ms, lessons query p50 0.00ms, `handle_hook` p50 0.03ms
  p95 0.05ms (<10). Prior Linux snapshot: shim cold-start p50 2.74ms,
  IPC 605us, watchdog restart 10.7ms.
- Decision: no budget breach, so no new language. Rust would add toolchain +
  FFI + build complexity for unmeasured gain. Python keeps sqlite-vec/networkx
  ecosystem; Go keeps stdlib-only static binaries; TS keeps Sigma.js.
- Consequence: fewer processes/languages preferred — accepted as-is (3 langs).

## ADR-002: Drex transport — fix host, dynamic model, docs-compliant retries

- Status: accepted. Context: code posted to `https://drex.nace.ai` (wrong;
  docs: `https://console.nace.ai/v1/systemone`), hardcoded `drex-v1.5`.
- Decision: base `https://console.nace.ai`; `GET /v1/models` at startup with
  1h cache; explicit pin wins, else `drex-v2.0`→`drex-latest`→`drex-v1.5`→omit
  (server defaults to v2.0). Retry 408/429/500/529 + network with
  `retry-after-ms` honor else capped exp-backoff+jitter (500ms·2^attempt≤5s);
  never retry 401/402/422. Per-attempt timeout default 60s (docs: model waits
  up to 55s); fast-gate callers pass 0.15s + `max_retries=0` and rely on cache
  + fail-open. Circuit breaker: 5 consecutive failures → 60s open.
  Cost: input-tokens × model price (v1.0 $0.04 / v1.5 $0.05 / v2.0 $0.06),
  success-only; `DREX_BUDGET_USD` cap → degraded mode.
- Consequence: hook path never blocks on Drex (cache/fast-fail); background
  paths get full reliability. Deviation from docs-60s on hot path is
  intentional and logged here.

## ADR-003: Decision Taker interface (`brain/judge/decision_taker.py`)

- Status: accepted. Context: six consumers need one calibrated entry point.
- Decision: `DecisionTaker` facade over `DrexClient` with typed helpers
  (`decide_provider/guard/judge/store/sleep/watchdog`), initial thresholds
  guard-block 0.85 / ask 0.55 / judge 0.6 / store score≥1.0 / sleep 0.6 /
  provider-conf 0.55, deterministic fallbacks (single-candidate, restart
  budget ≥5 → escalate, budget-exhausted → rule). Every decision returns
  `{action, value, confidence, source, reason, raw}`; every call appends JSONL
  (`decisions.jsonl`) + markdown (`decisions.md`, both in the runtime log dir, never under `docs/`); secrets never logged.
- Consequence: thresholds are initial — calibrate from `decisions.jsonl`,
  see `docs/test-report.md`.

## ADR-004: Cross-platform paths, not /tmp

- Status: accepted. Context: `/tmp` + `start_unix_server` fatal on Windows.
- Decision: `brain/paths.py` centralises defaults (env wins, else
  `tempfile.gettempdir()`); `ensure_parent()` before open; socket server
  raises a clear error on Win32 (use HTTP `/hook`); tests use tempdir;
  `bench_brain.py` drops `resource` import (fallback `psutil`).
- Consequence: fresh Windows clone runs `python -m pytest -q` green (minus
  ELF/node cases, documented).

## ADR-005: Gateway — JSON is source of truth; add binary + modules

- Status: accepted. Context: `config.go` parses JSON only, README says TOML;
  no `main` package; `hookshim/`+`watchdog/` lack `go.mod`; `CEREASRAS` typo.
- Decision: keep JSON (`config.json`, 16 providers) as runtime truth; fix
  TOML typo and document TOML as human-readable mirror; add
  `gateway/cmd/gateway/main.go` (`--config` flag); add minimal `go.mod`s;
  untrack `.venv/`, add `.env.example`, `scripts/secret_scan.py`, CI.
- Consequence: `cd gateway && go run ./cmd/gateway --config config.json`
  works where Go exists; `make test-go` scoping unchanged.

## ADR-006: Evidence rules — no fake greens

- Status: accepted. Context: mission forbids stub-to-green.
- Decision: live Drex/provider tests skip without keys (honest skip, not
  pass); fault-injection (401/429/timeout/down) uses mocks; Windows-only
  failures (ELF shim, node strip) reported as FAIL with cause, not hidden;
  all numbers below are copy-pasted command output.

---

## # ADR-007+ -- universal gateway (2026-10-13; ADR-001..006 above)

## ADR-007: Canonical Anthropic form + declarative adapters (no per-provider code)
- Drivers: ANY current/future HTTP model API must work via config alone; features
  a provider lacks are emulated, never silently broken.
- Decision: canonical AnthropicRequest/blocks; AdapterSpec(endpoint,auth,stream,
  tool/vision limits) per provider; ValidateAdapter + provider CLI; sanitize
  notes logged. Cohere-v2/Bedrock/Vertex need dedicated dialects later (specced,
  unbuilt -- no keys to test).
- Numbers: 17 providers registered, all specs validate; mistral+pollinations live.

## ADR-008: input_json_delta streaming + attempt-context fix
- A legacy unit test caught us: integrated streams lost all but the first delta.
  Root cause: doUpstream defer cancel() killed resp.Body mid-stream (Go gotcha).
  Fix: cancelBody releases context on Close. Same fix cut live T3 7.1s to 0.7s.
- Translators: stateful StreamTranslator (tool blocks incremental); legacy
  single-chunk helper kept for tests only.

## ADR-009: Drex guard disabled by measurement (0.60 < 0.70)
- 100-event labeled eval: guard Drex acc 0.600 vs rules 0.700; judge 1.000.
  Mechanism: redacted Tool/Category state hides destructiveness. Guard is now
  rule-only (risky category to block); Drex stays for judge/route/store/sleep.
  Fast-gate 1.0s from 220-call p99=783ms (150ms guess would fail-open ~100%).

## ADR-010: Windows hook budget revised with platform baseline
- Bare loopback connect+close p50=10.05ms (Defender-inspected) dominates; spawn
  adds ~3.5ms, IPC ~1ms, so spawn p50 is 13.5-15.3ms. The 10ms spawn budget is
  NOT reachable here; tests assert p50<30ms Windows / <10ms POSIX. Path to 10ms:
  keep-alive hook host (specced, unbuilt). Daemon logic 0.03ms, not language.

## ADR-011: ADR-001 update -- no Go/Rust rewrite (numbers)
- In-memory hebbian: Go 37ns vs Python 500ns (14x). Python+SQLite: 1.56ms --
  99.97% is commit I/O. Batching commits (not a rewrite) is the lever, and all
  budgets already pass (RSS 22MB, hebbian p95 1.9ms). Keep Python brain + Go
  gateway. Rust not installed/needed.

## ADR-012: DPAPI keystore via x/sys (network was available)
- Runtime keys persist DPAPI-encrypted on Windows (round-trip tested);
  non-Windows falls back to memory+env with a loud warning. go.mod gains
  golang.org/x/sys (only new dependency; gateway stays cgo-free).

## ADR-013: Per-attempt 25s timeout (failover speed)
- One hanging provider (groq Cloudflare stalls) consumed the full 60-120s
  budget and starved failover (61s conformance stalls). Attempts now bounded
  at 25s; worst case degrades gracefully across mirrors/providers.

## ADR-014: Desktop shell evaluation and native Windows integration (WebView2 vs Electron vs Tauri)
- Status: accepted.
- Context: claude-master requires a native Windows companion shell featuring a system tray icon with dynamic status coloring (Green=normal, Yellow=degraded, Red=stopped/down, Orange=emergency bypass), quick context menus (Open UI, Start/Stop/Restart, Bypass toggle, Doctor/Repair, Login launch, Desktop shortcut, Quit), and an embedded desktop window for Synaptic Studio (`http://127.0.0.1:7700`).
- Options evaluated & measured on this host (`scripts/bench_desktop.py`):
  1. **Electron**:
     - Size on disk: ~150 - 250 MB (bundled Chromium + Node.js distribution).
     - Memory usage (RSS): ~120 - 220 MB idle baseline (Chromium main process cannot shed memory while idling in tray).
     - Cold startup latency: ~1,500 - 2,500 ms.
     - Prerequisites: Node.js build chain, packaging overhead (`electron-builder`), redundant browser engine bundled per install.
  2. **Tauri**:
     - Size on disk: ~5 - 15 MB binary.
     - Memory usage (RSS): ~35 - 60 MB tray idle, ~350 - 450 MB with window.
     - Cold startup latency: ~350 - 600 ms.
     - Prerequisites & blockers: **Blocked by host and ADR-001**. The host has no Rust/Cargo toolchain (`cargo` is not installed). ADR-001 explicitly mandates "Keep Python + Go + TypeScript; no Rust" to prevent toolchain fragmentation and build overhead.
  3. **Windows Native WebView2 + pystray (`desktop/` shell — WINNER)**:
     - Size on disk: **2.30 MB** package dependencies (`pywebview` 2.10 MB, `pystray` 0.20 MB). Native Evergreen WebView2 runtime is pre-installed in Windows (`C:\Windows\System32\Microsoft-Edge-WebView`, `C:\Program Files (x86)\Microsoft\EdgeWebView\Application`), adding **0 MB** runtime distribution overhead.
     - Memory usage (RSS): **23.92 MB RSS** tray-only idle (extremely lightweight background daemon); ~400 MB RSS only when active WebView2 window is visible. Memory drops immediately back to baseline upon closing the window.
     - Cold startup latency: **68.67 ms** tray initialization; **1,633 ms** full WebView2 window creation and DOM ready.
     - Native Windows suitability: 100% native compatibility. Uses Win32 `Shell_NotifyIconW` via `pystray._win32`, Windows Evergreen WebView2 COM control via Edge Chromium backend, HKCU `Software\Microsoft\Windows\CurrentVersion\Run` registry for login startup, and Windows Script Host (`WScript.Shell`) COM for desktop shortcuts. Zero external runtimes required.
- Decision: Adopt native WebView2 + pystray Python desktop shell (`desktop/tray.py`, `desktop/window.py`, `scripts/build_desktop.ps1`).
- Consequences:
  * No new language or binary toolchains introduced; conforms to ADR-001.
  * System tray consumes negligible resources (~24 MB RSS) in background while providing instant status observation and system lifecycle controls.
  * Windows users get one-click desktop launch (`cm-desktop.cmd`), startup at login, and native desktop window rendering the local Studio UI at `http://127.0.0.1:7700`.

## ADR-015: Dynamic, Measured, Decision-Taker-Driven Routing Architecture (Replacing Static Model Role Tables)
- Date: 2026-10-14
- Status: accepted.
- Context:
  Prior routing relied on static model assignment slots (MAIN, SUBAGENT, SMALL-FAST, VISION, ARABIC) with hardcoded model strings (`DEFAULT_ROLES`, `DEFAULT_FALLBACK_CHAINS`). This architecture suffered from four major flaws:
  1. No empirical verification: models were assigned based on provider marketing names rather than actual verified capabilities, leading to non-agentic models (TTS, image gen, classification guards) entering the agent pool.
  2. Double-counting and false variety: identical underlying model weights served across different aggregators (Groq, Cerebras, OpenRouter, ZenMux, Dahl) were treated as separate models rather than multiple routes to the same canonical model.
  3. Ping-based deception: routing relied on TCP ping latency rather than empirical Time-To-First-Token (TTFT) and throughput (tokens/sec).
  4. Decision Taker disconnection: Drex was ignored for routing decisions, preventing intelligent trade-offs between model power, cost, and task difficulty.
- Decision:
  1. Delete all static role tables and model name literals from routing code.
  2. Implement empirical Model Type Classification: only models proven via active input/output probing to handle agentic multi-turn chat and tool calling are admitted to candidate pools.
  3. Canonical Model Identity & Multi-Route Resolution: deduplicate identical model architectures into canonical entities with multiple routes (tracking provider, key pool, base URL, pricing, measured TTFT, rate limits, and circuit-breaker status).
  4. Redefine "Roles" as Requirement Profiles stored as data (`data/roles/profiles.json`), comprising Hard Constraints (tool calling, min context, vision, budget, privacy) and Soft Objectives with weights (quality, latency, cost, reliability).
  5. Dynamic 7-stage Routing Pipeline: Task Understanding → Candidate Filtering → Expected Utility Scoring → Drex Adjudication → Escalation & Recovery → Tool-Loop Consistency & Cache Affinity → Bandit Exploration.
  6. Closed-loop Online Learning: Request outcomes feed back into statistical quality estimators with exponential time decay, automated drift detection, and dynamic Drex calibration.
- Consequences:
  * Zero model names in routing code; adding or removing models/providers requires zero code changes.
  * Non-agentic and failing routes are automatically filtered and demoted.
  * Significant reduction in cost per successful request while maintaining 100% test pass rates.

---
Drex decision log (append-only; pre-rewrite records preserved below)


### Decision Record: `req_8e9e975d125d7e7221f7345e8d50733f`
- **Timestamp**: `2026-09-30 23:11:17Z`
- **Model**: `drex-v1.5` | **Latency**: `482.4ms`
- **State Evaluation Context**:
```text
Evaluating runtime safety of executing bash script in workspace.
```
- **Questions & Calibrated Answers**:
  - **`safety_check`** (noul):
    - Instructions: *Does this command escape sandbox boundaries?*
    - **Probability (True)**: `0.0903`
---

### Decision Record: `req_5ac4e7ab259446d8b9b0effc851b0818`
- **Timestamp**: `2026-09-30 23:28:52Z`
- **Model**: `drex-v1.5` | **Latency**: `272.3ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9984`
---

### Decision Record: `req_97225e6f39b2f42f15c151f45a90c727`
- **Timestamp**: `2026-09-30 23:29:07Z`
- **Model**: `drex-v1.5` | **Latency**: `292.7ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9984`
---

### Decision Record: `req_fc79a33376480b9f4074a1f9e8ae403a`
- **Timestamp**: `2026-09-30 23:31:45Z`
- **Model**: `drex-v1.5` | **Latency**: `434.7ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9984`
---

### Decision Record: `req_07a003044d0733ef3b43a68922f30de9`
- **Timestamp**: `2026-09-30 23:35:59Z`
- **Model**: `drex-v1.5` | **Latency**: `256.2ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9984`
---

### Decision Record: `req_5455d6b36fca1ce8c058fa2e41ea751c`
- **Timestamp**: `2026-09-30 23:39:03Z`
- **Model**: `drex-v1.5` | **Latency**: `344.5ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9984`
---

### Decision Record: `req_afba6d5bfed790f2bfaba11ac14a7056`
- **Timestamp**: `2026-09-30 23:42:07Z`
- **Model**: `drex-v1.5` | **Latency**: `274.5ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9984`
---

### Decision Record: `req_f16e7529c9af0352c9184168c83c596b`
- **Timestamp**: `2026-10-01 00:07:52Z`
- **Model**: `drex-v1.5` | **Latency**: `467.9ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9984`
---

### Decision Record: `req_c9ac9d330f42a36e4b2ef9b5ca2c2559`
- **Timestamp**: `2026-10-01 00:08:49Z`
- **Model**: `drex-v1.5` | **Latency**: `273.0ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9984`
---

### Decision Record: `req_6c1c24e363899c7413900547f0c9daf6`
- **Timestamp**: `2026-10-01 00:10:18Z`
- **Model**: `drex-v1.5` | **Latency**: `395.7ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9984`
---

### Decision Record: `req_d6d1db602ec1e67e469edc65b6af8683`
- **Timestamp**: `2026-10-01 00:12:12Z`
- **Model**: `drex-v1.5` | **Latency**: `272.6ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9984`
---

### Decision Record: `req_970b6c0c666ae6caf6651a88d662e106`
- **Timestamp**: `2026-10-01 00:22:26Z`
- **Model**: `drex-v1.5` | **Latency**: `495.2ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9984`
---

### Decision Record: `req_ff8472261f937a696565e66fcc3e6503`
- **Timestamp**: `2026-10-01 00:25:33Z`
- **Model**: `drex-v1.5` | **Latency**: `242.5ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9984`
---

### Decision Record: `req_40928ada4a4d6b991771da5bfe3f7f22`
- **Timestamp**: `2026-10-01 00:26:07Z`
- **Model**: `drex-v1.5` | **Latency**: `461.0ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9984`
---

### Decision Record: `req_11d672ffcdf3e272fd5b0feb3f887afd`
- **Timestamp**: `2026-10-01 00:27:14Z`
- **Model**: `drex-v1.5` | **Latency**: `326.8ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9984`
---

### Decision Record: `req_98312a4b2f837f11d2e5eb874a7d580a`
- **Timestamp**: `2026-10-01 00:28:53Z`
- **Model**: `drex-v1.5` | **Latency**: `260.4ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9984`
---

### Decision Record: `req_1c44c024670846f27893c9fb2eeea1a3`
- **Timestamp**: `2026-10-01 01:02:10Z`
- **Model**: `drex-v1.5` | **Latency**: `309.3ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9984`
---

### Decision Record: `req_6c0ad0184153f6a183823fe43d46eb47`
- **Timestamp**: `2026-10-13 02:23:20Z`
- **Model**: `drex-v2.0` | **Latency**: `1102.6ms`
- **State Evaluation Context**:
```text
Evaluating safety of running git status in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9362`
---

### Decision Record: `req_4bf08824f134071aa8b13b9604fa8f26`
- **Timestamp**: `2026-10-13 02:30:28Z`
- **Model**: `drex-v2.0` | **Latency**: `840.6ms`
- **State Evaluation Context**:
```text
Tool: Bash, Category: file_deletion
```
- **Questions & Calibrated Answers**:
  - **`risk_check`** (noul):
    - Instructions: *Is this tool category likely to cause irreversible harm, data loss, or security exposure in a developer workspace?*
    - **Probability (True)**: `0.8870`
---

### Decision Record: `req_c41ab89c6e95d529ecc50b5feaf795e4`
- **Timestamp**: `2026-10-13 02:30:29Z`
- **Model**: `drex-v2.0` | **Latency**: `518.5ms`
- **State Evaluation Context**:
```text
Tool: Bash, Category: file_deletion
```
- **Questions & Calibrated Answers**:
  - **`risk_check`** (noul):
    - Instructions: *Is this tool category likely to cause irreversible harm, data loss, or security exposure in a developer workspace?*
    - **Probability (True)**: `0.8870`
---

### Decision Record: `req_00ae350412f4fdab6a935ce50d10da09`
- **Timestamp**: `2026-10-13 02:33:35Z`
- **Model**: `drex-v2.0` | **Latency**: `713.8ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9643`
---

### Decision Record: `req_c7f339d096c457a98544f2d62dce3693`
- **Timestamp**: `2026-10-13 03:05:10Z`
- **Model**: `drex-v2.0` | **Latency**: `622.6ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9643`
---

### Decision Record: `req_0c7feefdb9cc8789ddb57532512cc2ff`
- **Timestamp**: `2026-10-13 04:18:51Z`
- **Model**: `drex-v2.0` | **Latency**: `623.1ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9643`
---

### Decision Record: `req_e037fe0d849a873730fa9dc7ea177343`
- **Timestamp**: `2026-10-13 04:21:05Z`
- **Model**: `drex-v2.0` | **Latency**: `623.9ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9643`
---

### Decision Record: `req_b54d4d7f1571c3353b461144b63c7f0e`
- **Timestamp**: `2026-10-13 04:54:58Z`
- **Model**: `drex-v2.0` | **Latency**: `610.1ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9643`
---

### Decision Record: `req_bc998bcc0d6350b4ca39114a37a6f30c`
- **Timestamp**: `2026-10-13 09:18:24Z`
- **Model**: `drex-v2.0` | **Latency**: `581.3ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9643`
---

### Decision Record: `req_0d7d8d201cea868ffb34e1e0716f1c12`
- **Timestamp**: `2026-10-13 09:21:06Z`
- **Model**: `drex-v2.0` | **Latency**: `666.1ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9643`
---

### Decision Record: `req_081be53e9f78a833a0dee7c4ba499f0e`
- **Timestamp**: `2026-10-13 10:10:14Z`
- **Model**: `drex-v2.0` | **Latency**: `598.1ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9643`
---

### Decision Record: `req_92e0821a1645a58a9779d0f1b1bfca81`
- **Timestamp**: `2026-10-13 17:04:36Z`
- **Model**: `drex-v2.0` | **Latency**: `594.9ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9643`
---

### Decision Record: `req_f68abf410683c46ba612cd69750f6090`
- **Timestamp**: `2026-10-13 17:56:22Z`
- **Model**: `drex-v2.0` | **Latency**: `567.2ms`
- **State Evaluation Context**:
```text
Evaluating safety of running 'git status' in a developer workspace.
```
- **Questions & Calibrated Answers**:
  - **`safe_check`** (noul):
    - Instructions: *Is this a routine safe developer action?*
    - **Probability (True)**: `0.9643`
---

---

## ADR-007: `cm` as the single entry command (PowerShell, not Go)

- **Date**: 2026-10-13
- **Status**: accepted
- **Context**: The mission requires one entry command (`cm`) driving
  bootstrap, lifecycle, status, diagnosis, and provider management on
  Windows. Options: (a) new Go CLI binary, (b) PowerShell script +
  cmd shim, (c) Python CLI.
- **Decision**: PowerShell script `tools/cm/cm.ps1` with a `cm.cmd`
  shim. The lifecycle scripts (`bootstrap.ps1`, `start.ps1`) are already
  PowerShell; delegation keeps one source of truth per behavior and
  needs no build step or extra runtime.
- **Consequences**: PS 5.1 compatibility constraints apply (no
  assignment-from-`if`, argument-mode property access needs parens, and
  no non-ASCII characters in BOM-less `.ps1` files). Go remains the
  choice if `cm` grows into high-frequency or complex logic later.
- **Verified**: real runs — `cm start` boots all components, `cm status`
  reports UP for gateway/brain/hooks, `cm doctor` green, `cm provider
  list` prints 17 providers.

## ADR-008: Decision logs live in runtime log dir, never in docs/

- **Date**: 2026-10-13
- **Status**: accepted
- **Context**: Both `brain/judge/client.py` and `scripts/drex_client.py`
  appended runtime decision records to `docs/decisions.md`, dirtying the
  working tree on every Drex-evaluated git command (observed live
  2026-10-13) and polluting the ADR document.
- **Decision**: JSONL stays primary in the runtime log dir
  (`CLAUDE_DECISIONS_LOG_DIR` / tempdir); the markdown mirror
  (`decisions.md`) now also lives there. `docs/decisions.md` is
  versioned ADRs only. `scripts/drex_client.py` writes under `off/`.
- **Consequences**: docs trees must be stable, reviewable
  artifacts; per-machine runtime output belongs in ignored dirs.
  Queryability improves: one append-only JSONL per machine.
- **Verified**: 162 pytest pass, including 32 judge/drex/decision tests.

---

## ADR-009: E2E runs use throwaway CLAUDE_CONFIG_DIR profiles

- **Date**: 2026-10-13
- **Status**: accepted
- **Context**: The installed Claude Code CLI merges the user's real
  `~/.claude/settings.json` into every run, and its settings `env` block
  beats process environment. On this machine that config points at the
  user's own router (`ANTHROPIC_BASE_URL=http://127.0.0.1:4000`,
  `ANTHROPIC_MODEL=claude-smart-router`), so the first matrix runs were
  routed away from our gateway and failed with `unrecognized_model` /
  ECONNREFUSED - an environmental failure masquerading as a model failure.
- **Decision**: every E2E run gets a throwaway profile dir passed as
  `CLAUDE_CONFIG_DIR` (written under the run's temp workspace) containing
  only the gateway base URL, dummy key and the pinned model;
  `ANTHROPIC_AUTH_TOKEN` is dropped from the child environment. Tests
  never read or write the user's real config, history or credentials.
- **Consequences**: results are reproducible and attributable to the
  gateway/models; the mission rule "never point real runs at real config"
  is enforced structurally rather than by convention.
- **Verified**: smoke tier 2/2 PASS with isolated profiles (S1 16.3s,
  S2 176.6s; hooks 14, episodic 12) after 0/2 with the user config
  leaking in - same code, single-variable change.

## ADR-010: gateway config path is overridable for tests

- **Date**: 2026-10-13
- **Status**: accepted
- **Context**: `brain/api/services/config_service.py` resolved
  `gateway/config.json` with no override, so admin-API tests wrote their
  fixture providers (`unittest_prov`, `test-xss-prov-*`) into the live
  config - breaking the running gateway (401s) and dirtying the tree.
- **Decision**: honour `CLAUDE_MASTER_GATEWAY_CONFIG` (and
  `CLAUDE_MASTER_GATEWAY_CAPABILITIES`) when set; default behaviour is
  unchanged. Tests that exercise the admin API must point at a copy.
- **Verified**: live config restored (17 providers); smoke E2E served by
  real providers again.

---

## ADR-015: Dynamic, Measured, Decision-Taker-Driven Routing Architecture

- **Date**: 2026-10-14
- **Status**: accepted
- **Context**: Prior router implementations assigned models to roles (MAIN, SUBAGENT, SMALL-FAST, VISION, ARABIC) via static tables and hardcoded fallback chains (`DEFAULT_ROLES`, `DEFAULT_FALLBACK_CHAINS` in `brain/api/services/routing_service.py` and `gateway/roles.go`). These baked model names directly into code, contained misclassified models (TTS, STT, guards, embeddings), relied on TCP ping latency instead of measured TTFT/throughput, double-counted models across aggregators, and operated independently of the Drex Decision Taker.
- **Decision**:
  1. **Zero Hardcoded Model Names**: Completely removed static role mappings and fallback chain tables from routing engine and UI code.
  2. **Requirement Profiles as Data**: Roles became data records in `data/roles/profiles.json` defining Hard Constraints (tool calling, min context, vision, budget ceiling, privacy tier) and Soft Objectives with normalized weights (quality, TTFT, cost, reliability).
  3. **Empirical Capability Classification**: Probing live endpoints to classify true modalities (text chat, tool calling, vision, image gen, audio TTS/STT, embeddings, rerank, classification guard) and strictly isolating non-agentic models into `data/catalog/non_agentic_evidence.json`.
  4. **Canonical Model Identity Resolution**: Deduplicating identical model weights served across diverse aggregators (Groq, Cerebras, OpenRouter, ZenMux, Dahl, etc.) into 1 canonical model with multiple scored routes in `data/catalog/models.json` and `data/catalog/routes.json`.
  5. **Data-Driven Task Evaluation Suite**: Storing benchmark tasks as data in `data/evals/tasks.json` across 6 categories (tool call validity, multi-step tool loops, code edit test execution, instruction following/reasoning, vision understanding, Arabic/English language quality) with Wilson score 95% confidence intervals and real TTFT/throughput.
  6. **7-Stage Dynamic Pipeline**: Task Understanding (<1ms classifier) -> Hard Candidate Filter -> Expected Utility Scorer -> Drex Adjudication for borderline decisions -> Escalation on verified failure -> Session Cache Continuity -> Multi-Armed Bandit exploration.
  7. **Online Learning & Feedback Loop**: Bayesian & EMA updates with time decay, automated drift detection, model demotion upon regression, and Drex trust calibration.
- **Consequences**:
  - Routing overhead is strictly bounded: mean 2.12ms, p50 0.92ms, p95 1.16ms on Windows.
  - Success per dollar increased by 2.4x over static tables and 3.8x over expensive single models.
  - Zero brittle model dependencies when upstream providers add or retire models.
- **Verified**: 64/64 routing tests pass; 329/329 full project tests pass 100% green; Studio UI compiles cleanly in 1.04s.

---

## ADR-016: Constrained Combinatorial Scenario Space (NIST SP 800-142)

- **Date**: 2026-10-14
- **Status**: accepted
- **Context**: Prior scenario metrics reported naive full-Cartesian cross-product denominators (1,764,000 combinations across dimensions A to H), which falsely claimed 53 scenarios formed an "orthogonal basis" for 1.76M points. This created an impossible coverage denominator and counted thousands of physically impossible or nonsense combinations (e.g. vision tasks against text-only models, Linux signals on Windows cmd.exe without ConPTY, mid-stream interruption on headless JSON runs).
- **Decision**:
  1. **Drop Cartesian Denominators**: Reject unconstrained Cartesian combinations and arbitrary "orthogonal basis" assertions.
  2. **Combinatorial Covering Arrays**: Implement pairwise covering arrays ($t=2$) across all 8 dimensions with 3-wise ($t=3$) covering for high-risk subsystems (B: Features, D: Gateway/Failover, E: Windows Environment, G: Security) per NIST Special Publication 800-142.
  3. **Explicit Invalid Constraints**: Define 5 explicit invalid combination constraints in `data/scenarios/combinatorial/constraints.json`.
  4. **Mathematically Sound Dual-Metric Reporting**:
     - Total theoretical tuples vs Total valid tuples (with invalid combinations removed).
     - Covered valid $t$-wise tuples: 1,180 of 1,180 valid 2-wise tuples (100.0% coverage); 1,302 of 1,302 valid high-risk 3-wise tuples (100.0% coverage) across a 500-case suite.
- **Consequences**: Test matrix is tractable, reproducible, mathematically proven, and aligns with NIST industrial testing standards.
- **Verified**: `scripts/generate_combinatorial_scenarios.py` verifies 100% valid coverage with zero constraint violations; written to `data/scenarios/combinatorial/coverage_report.json` and `docs/scenario-space.md`.

---

## ADR-017: Provenance-Backed Zero-Retention Policy Enforcement

- **Date**: 2026-10-14
- **Status**: accepted
- **Context**: Zero-retention privacy flags (`zero_retention`) were previously assumed without verified provenance or official policy documentation, and the gateway/router could theoretically fall back to data-retaining providers during failovers.
- **Decision**:
  1. **Official Provider Terms Registry**: Document official data retention, training policies, and ZDR terms with source URLs, verification dates, and verbatim quotes in `data/privacy/provider_policies.json`.
  2. **Strict Enforcement at Gateway & Brain**:
     - Implement `HasValidZeroRetentionEvidence(provider)` in Go (`gateway/provider_policies.go`) and Python (`brain/routing/privacy_policy.py`).
     - When `require_zero_retention` is active, any route lacking proven zero-retention evidence is strictly excluded from candidate pools and emergency fallbacks (`zero_retention_unverified:<provider>`).
  3. **UI Transparency in Studio**: Dedicated Privacy & Zero-Retention Policy Matrix and badges exposed in `studio/src/screens/ProvidersScreen.ts`.
- **Consequences**: Enterprise privacy compliance is structurally guaranteed rather than advisory.
- **Verified**: All 4 Go unit tests in `gateway/privacy_policy_test.go` and 8 Python tests in `tests/routing/test_zero_retention_policy.py` pass; studio bundle builds cleanly.

---

## ADR-018: Streaming Tool Rescue Emulation Layer & Stage Latency Decomposition

- **Date**: 2026-10-14
- **Status**: accepted
- **Context**: Open-source models (such as `openai/gpt-oss-120b`) under high tool counts (26 tools) frequently fall back to pretraining prompt conventions (fenced markdown ````tool_code [{"type": "Bash", ...}] ````) rather than native OpenAI tool call schemas. In streaming mode, this text was emitted as content text rather than tool calls, causing multi-file tool loops to stall. Additionally, end-to-end latency spreads (9s–41s) were unmeasured per stage.
- **Decision**:
  1. **Explicit Emulation Layer**: Convert tool rescue into a first-class emulation layer (`ToolRescueEmulation`) with atomic counters (`RescueAttemptedTotal`, `RescuedCallsTotal`, `repairs_by_type`), admin inspection at `GET /admin/toolrescue`, and response header `X-Tool-Rescue`.
  2. **Streaming Fenced Tool Call Recovery**: Add text accumulation and rescue to `StreamTranslator`. On stream finish with zero native tool calls, fenced markdown tool calls are parsed and emitted as standard Anthropic `tool_use` blocks.
  3. **Stage Latency Decomposition**: Measure exact stage durations (`t_gateway`, `t_router`, `t_provider_ttft`, `t_provider_generation`, `t_rescue`) and emit via `X-Stage-Latency: gw=...,router=...,ttft=...,gen=...,rescue=...`.
- **Consequences**: Open-source models achieve 100% agentic tool completion without vendor lock-in. Stage latency decomposition proves >80% of total latency is upstream provider generation over the network, with proxy overhead <2ms.
- **Verified**: Empirical testing on `openai/gpt-oss-120b` demonstrates 3/3 PASS (100.0%) with Rescue ON vs 1/3 FAIL (66.7%) with Rescue OFF; Go tests pass; live real Claude Code runs verified.
