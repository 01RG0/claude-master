# R1 Review — Wave 1 Python Core (B1 / B2 / B3 / B8)

**Reviewer:** independent (R1)  
**Branch reviewed against:** working tree on `agent/R1-review` (feature code untracked / present as claimed done)  
**Date:** 2026-09-30  
**Pytest:** `python3 -m pytest tests/brain/ -q` → **70 passed**, 1 warning (`asyncio_mode` unknown config) in ~1.46s  

Alignment skim: `contracts/schema.sql` (authoritative tables + deferred `brain_node_vectors`); `research/errata.md` §3 (Drex fail-open / redaction / cache), §7 (license quarantine).

---

## Verdict summary

| Card | Module | Verdict |
|------|--------|---------|
| B1 | `brain/store/` | **CHANGES-REQUESTED** |
| B2 | `brain/learning/` | **CHANGES-REQUESTED** |
| B3 | `brain/guard/` | **CHANGES-REQUESTED** |
| B8 | `brain/judge/` | **CHANGES-REQUESTED** |

No feature rewrites performed. No new tests added (missing acceptance items need APIs or measured budgets first).

---

## B1 — Store (`brain/store/`, `tests/brain/test_store.py`)

**Verdict: CHANGES-REQUESTED**

### Acceptance checklist
| # | Criterion | Status |
|---|-----------|--------|
| 1 | DB init from `contracts/schema.sql` | **Met** — tables present; FTS virtual tables created |
| 2 | sqlite-vec load + cosine rank on 384-d | **Not met** |
| 3 | Contradiction invalidates edge, keeps history | **Met** — `TemporalStore.add_fact` + test |
| 4 | Recursive CTE neighbors depth ≤3 within 2ms | **Partial** — CTE works (test depth 2); depth-3 path & budget unmeasured |

### Issues
- **[HIGH]** No embedding upsert / cosine KNN API; `test_store.py` never exercises vector ranking. Runtime probe: `BrainDB.vec_enabled == False` even though `pyproject.toml` lists `sqlite-vec` — AT2 unprovable.
- **[MED]** Performance budgets (vector top-5 &lt; 3ms; traversal &lt; 2ms) **unmeasured** — no bench assertions.
- **[LOW]** `add_fact` docstring says invalidate when weight differs; implementation invalidates any same `(src,tgt,rel)` triple.

### License / secrets
- Attribution comments + root `NOTICE` (graphiti Apache-2.0 algorithm port) — no GPL/AGPL paste observed.
- No secret logging in store paths.

### Schema alignment
- Loads `contracts/schema.sql` idempotently; `brain_node_vectors` correctly deferred to runtime after vec load (matches schema NOTE).

---

## B2 — Learning (`brain/learning/`, `tests/brain/test_learning.py`)

**Verdict: CHANGES-REQUESTED**

### Acceptance checklist
| # | Criterion | Status |
|---|-----------|--------|
| 1 | Hebbian ↑ on R=1.0, ↓ on R=-0.8 | **Partial** — LTP(+1)/LTD(−1) tested; R=−0.8 path not asserted |
| 2 | FSRS-5 power-law retention | **Partial** — monotonic decay + formula shape; no numeric golden curve |
| 3 | Spreading from 2 seeds; causal/reinforce; refractory | **Partial** — role/refractory OK; **single-seed** tests only |
| 4 | Spreading 1k nodes &lt; 5ms | **Not met** — unmeasured |

### Issues
- **[MED]** AT3: no dual-seed activation test; card requires starting from 2 seeds.
- **[MED]** Performance budgets (spreading &lt; 5ms; synaptic update &lt; 2ms) **unmeasured**.
- **[LOW]** LTD helper hard-codes reward=−1.0; card example R=−0.8 not covered.

### License / secrets
- Clean-room FSRS / spreading / Hebbian with MIT attributions in module headers and `NOTICE`. No GPL/AGPL paste. No secrets.

---

## B3 — Guard (`brain/guard/`, `tests/brain/test_guard.py`)

**Verdict: CHANGES-REQUESTED**

### Acceptance checklist
| # | Criterion | Status |
|---|-----------|--------|
| 1 | 4× repeating action-observation → stuck / breaker | **Met** (via `StuckResult.is_stuck`) |
| 2 | Ping-pong A→B→A→B | **Met** |
| 3 | Structural normalizer ignores UUID/timestamps | **Met** as `_event_key` (card name `_event_eq`) |
| 4 | Socket hook response &lt; 4ms | **Not met** — **zero** `socket_server` tests |

### Stuck detector — 5 patterns?
Implemented **4** patterns (`repeating_action_observation`, `repeating_action_error`, `monologue`, `pingpong`). Module header claims “5-pattern”; class docstring says “four”. Card goal: OpenHands **5**-pattern detector.

### Issues
- **[HIGH]** AT4: no Unix-socket IPC tests; hook latency budget &lt; 4ms **unmeasured**; normalizer &lt; 0.5ms **unmeasured**.
- **[MED]** Fifth OpenHands loop pattern missing / undocumented — card/title vs implementation mismatch.
- **[LOW]** No explicit “circuit breaker” latch beyond returning `is_stuck` + nudge (may be intentional).

### License / secrets
- MIT algorithm reimplementation claimed; listed in `NOTICE`. Socket failsafe does not log payload secrets (debug logs exception type only). OK.

---

## B8 — Judge (`brain/judge/`, `tests/brain/test_judge.py`)

**Verdict: CHANGES-REQUESTED**

### Acceptance checklist
| # | Criterion | Status |
|---|-----------|--------|
| 1 | Dangerous cmds classified rejected | **Partial** — local regex → Drex; reject only if `noul > 0.85`; no hard local deny |
| 2 | Dev tools approved (`git status`, `go test`, `pytest`) | **Met** (`pytest` via `python3 -m pytest` or `not_risky` for bare `pytest`) |
| 3 | Cache identical queries &lt; 0.2ms, no network | **Partial** — functional cache OK; latency **unmeasured** |
| 4 | Timeout/error → fail-open + warning logged | **Partial** — fail-open returns `_fail_open`; **no warning log** |

### Drex / errata §3
| Requirement | Status |
|-------------|--------|
| Fail-open on timeout/HTTP error | **Met** (client + gating) |
| In-memory cache | **Met** (`DrexCache`) |
| No secrets in Drex requests | **Met** — redacted `Tool:/Category:`; `test_raw_command_not_in_drex_state` |

### Issues
- **[HIGH]** AT4 incomplete: `DrexClient.evaluate` swallows exceptions with silent `{"_fail_open": True}` — card requires **warning logged**.
- **[MED]** AT1: catastrophic commands are not deterministically rejected without a cooperative Drex response; under fail-open they are **allowed** (errata-aligned, but AT wording says “rejected”).
- **[MED]** Cache hit latency budget &lt; 0.2ms **unmeasured**.
- **[LOW]** Credential-exfil examples not assertively tested for `allow=False` under mocked high-noul Drex.

### License / secrets
- No GPL/AGPL. API key used in Authorization header only; not logged. Decision log writes Drex **state** (gating keeps this redacted). OK for gating path.

---

## Cross-cutting

| Topic | Finding |
|-------|---------|
| License quarantine | No GPL/AGPL paste in reviewed Python; `NOTICE` present with MIT/Apache attributions |
| Secrets | Not logged in judge fail-open path; gating redacts before Drex |
| Performance | **All card budgets unmeasured** across B1–B3–B8 (and B2 spreading) |
| Pytest | 70/70 green — does not imply acceptance/perf coverage |

---

## Required follow-ups (builders)

1. **B1:** Ship vec upsert + cosine search; install/verify `sqlite-vec`; add ranking + latency tests.  
2. **B2:** Dual-seed spreading test; measure 1k-node activation; optional R=−0.8 case.  
3. **B3:** Add socket e2e/latency test; resolve 4 vs 5 patterns; rename or alias `_event_eq` if required by card.  
4. **B8:** Log warning on fail-open; add cache-hit latency assertion (&lt;0.2ms); clarify hard-reject vs Drex-gated reject for AT1.

**Overall:** **CHANGES-REQUESTED** for all four cards. Functional cores largely present and unit-tested; critical acceptance holes are vector search (B1), perf budgets (all), socket IPC (B3), and fail-open warning (B8).
