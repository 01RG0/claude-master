# Resume Point (2026-10-13, session 2 continuation state)

Branch `rewrite`, HEAD at bridge of the cm/CI/metrics commits (see
`git log --oneline -15`). Baseline frozen in `docs/cleanup-baseline.md`
(pytest 162 pass, Go gateway/hookshim/watchdog pass, studio 17 pass -
re-verified mid-session via `cm test`).

## Done and verified this session

1. **cm CLI complete-ish** (tools/cm/cm.ps1 + cm.cmd + completions.ps1):
   setup, start, stop, restart, status, doctor, logs, config, provider,
   key list, model list|pin|ban, report, test, bench, e2e, explain,
   alerts. All verified live on the real system (status shows UP for all
   components, doctor green, explain prints a real decision record,
   alerts proven NEW->seen->quiet).
2. **Two real bugs fixed**: docs/decisions.md runtime pollution (ADR-008)
   and start.ps1 `$Args` parameter collision (startup was broken).
3. **CI**: Python/Go/vet/studio jobs on ubuntu + a windows job including
   PS 5.1 parse-check of every committed .ps1 (tools/cm/parse_check.ps1)
   and CI-tolerant cm doctor.
4. **Metrics into cm status** from real data: requests today, top
   mapped models, Drex decisions today, last test result (cm test
   writes off/last-test.json), cm explain joins decisions.jsonl.
5. Dead-code purge, .gitignore hardening, detector ASCII-safe output,
   README rewritten around cm, ADR-007/008 recorded.
6. Note: untracked dirs `brain/api/`, `studio/src/components|i18n|state`,
   `scripts/bench_desktop.py` appeared mid-session from a CONCURRENT
   session (brain API layer + studio components). Not mine, not junk -
   left untouched; coordinate before committing or deleting.

## Next actions, in order

1. **`cm explain` deep-join**: gateway.gb request-id tracking vs
   decisions.jsonl currently only textually matches by time window;
   add a real request id in gateway traffic records and join exactly.
2. **Part 5 rest**: token/cost metrics (usage fields exist in
   decisions.jsonl and per-request sums in gateway logs), trend reports
   (`cm report --trend` over stored per-commit test/bench results),
   studio drill-down (click a request -> every step + Drex decision).
3. **E2E mission (the big one)**: expand scripts/e2e_claude_matrix.py
   beyond the current 10 scenarios to the full Part-2 matrix (N=5 reps,
   PTY interactive driver for slash commands/permissions/interrupts,
   independent oracles, mid-session failover/429/budget-stop residency
   tests, spend caps, per-commit result storage, cm e2e matrix/report
   wiring).
4. **Part 3 optimizations** only behind measured regressions; budgets
   live in docs/benchmarks.md.
5. Version/release tooling: CHANGELOG.md (keep-a-changelog), semver,
   one-command release with checksums.

## Gotchas learned (do not re-hunt)

- PS 5.1: no `$x = if ...`; argument-mode needs `($hash.key)`; no
  unicode in BOM-less ps1 (em dash -> 0x94 -> curly-quote string
  delimiter); no `ConvertFrom-Json -AsHashtable`; `$PROFILE:` needs
  `${PROFILE}`. parse_check.ps1 catches all of this pre-merge.
- `start.ps1` blocks while babysitting children: run via BACKGROUND
  process or an interactive shell, never a SYNC wrapper.
- Never name a PowerShell parameter `$Args` (automatic variable).
- Runtime outputs (off/, temp logs) are gitignored; docs/decisions.md
  is ADR-only (ADR-008).

## Session 3 (E2E harness work, same day)

- `scripts/e2e_claude_matrix.py` refactored: scenario registry (S1-S10 with
  per-scenario setup + ground-truth oracle), `--scenario/--model/--repeat/
  --tier/--json-out/--resume/--min-pass-rate/--max-runs/--gateway-port`,
  per-commit JSON artifacts, pass-rate summary.
- REAL FINDING + FIX: the installed CLI merged the user's real
  `~/.claude/settings.json` (their router + model) into every run -> runs
  never reached our gateway. Fixed with a throwaway `CLAUDE_CONFIG_DIR`
  per run (ADR-009). Smoke tier now 2/2 PASS via real providers
  (S1 16.3s, S2 176.6s; hooks 14, episodic 12 nodes).
- REAL FINDING (concurrent session's WIP, fix left uncommitted in its
  untracked `brain/api/services/config_service.py`): admin-API tests wrote
  fixture providers into the LIVE gateway/config.json, breaking routing
  (401s). Added `CLAUDE_MASTER_GATEWAY_CONFIG` env override (ADR-010);
  live config restored to 17 providers.
- S2 is slow (176s for one `python check.py` task): provider/model
  choice + CLI retries - prime candidate for the Part 3 latency work.
- Next: extend to the full Part-2 matrix (interactive PTY driver, MCP
  stdio+HTTP, plugins, hooks all events, LSP, permissions, failover
  residency tests), stats over N reps, `cm e2e report`, per-commit trend.

## Session 4 (latency investigation + config data fixes)

Measured with the real CLI (see docs/benchmarks.md for the full table):

- S2 n=3: 13.0s / 88.6s / 170.9s (median 88.6, p95 170.9), 3/3 verified.
  The 176s outlier is REAL and reproduces; it is not harness flakiness.
- Traffic attribution over 267s / 67 requests: 45% of upstream calls are
  aux (1 msg, 0 tools, 1-11s each); main tool-turns hit the small
  `ministral-8b-latest` 20/35 times.
- FIXED (verified): dead provider entries were burning every request
  (groq/cerebras 404 chain + 400/401/403 from unkeyed/unknown providers).
  Config now carries live ids (groq `openai/gpt-oss-120b`,
  `qwen/qwen3.8-27b`; cerebras `gpt-oss-120b`, `qwen-3.8-27b`);
  `provider.exe validate` = "all adapter specs valid"; a measured run
  showed 0 provider HTTP failures (was a failure chain per request).
- FIXED: `provider.exe scan` reported false retirements - `diffModels`
  compared raw strings (Gemini's `models/` prefix) and treated the `*`
  wildcard as a literal model. Normalized + wildcard-skipped, regression
  tests in gateway/cmd/provider/main_test.go.
- Still open (measured, ordered): (1) aux-call reduction on the hot path
  (45% of calls) - cache/dedupe; (2) routing tool-heavy turns away from
  ministral-8b; (3) `provider.exe pin|ban` is a STUB (prints guidance,
  hides nothing) - persist bans and honour them at startup.
- Heads-up for the other session: admin-API tests still write fixture
  providers into the live gateway/config.json (re-polluted twice today);
  set CLAUDE_MASTER_GATEWAY_CONFIG to a copy (ADR-010) - the fix is
  already in brain/api/services/config_service.py (uncommitted, theirs).
