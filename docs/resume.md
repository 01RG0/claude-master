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
