# Resume Point (2026-10-13, session continuation state)

Branch `rewrite`. Baseline frozen in `docs/cleanup-baseline.md`
(pytest 162 pass, Go gateway/hookshim/watchdog all pass, studio 17 pass).
All changes below are committed; `git status` clean apart from ignored
runtime output (`off/`, temp logs).

## Done and verified this session (commits: c8859e4, 78db0ce, cf4210e,
   f11d6fd + pending docs commit)

1. Repo audit + classification of in-flight work; detection corpus
   (`data/`, `scripts/detect_all.py`, `docs/detector-report.md`) and the
   live model-validation feature committed.
2. Junk removed: one-off Cohere/Gemini probes, `generate_cards.py`,
   `bench_hook_win.py` (superseded by `bench_hookhost.py`),
   `cmd/dbgvalidate` — all moved to ignored `scripts/attic/`.
3. `.gitignore` hardened (binaries incl. `*.exe~`, `off/`, logs, caches).
4. REAL BUG FIXED: Drex decision logs no longer append to
   `docs/decisions.md` (runtime log dir only; scripts/drex_client.py
   writes under `off/`). Verified: 162 pytest pass.
5. REAL BUG FIXED: `scripts/start.ps1` `$Args` parameter collided with
   the PowerShell automatic variable -> `Start-Process -ArgumentList`
   empty -> startup always failed at brain spawn.
6. `cm` CLI shipped (`tools/cm/cm.ps1` + `cm.cmd`): setup, start, stop,
   restart, status, doctor, logs, config, provider, report. Verified
   live: `cm start` boots brain+gateway+watchdog, `cm status` shows all
   UP, `cm doctor` green, `cm provider list` 17 providers. ADR-007/008
   appended to docs/decisions.md. README rewritten around `cm` (stale
   config.toml reference removed).

## Next actions, in order

1. **Commit the pending docs changes** (README + ADRs, `git add README.md
   docs/decisions.md docs/resume.md docs/cleanup-baseline.md`).
2. **Part 4 extras**: `cm e2e run|matrix|replay|report` delegating to
   `scripts/e2e_claude_{live,matrix}.py`; `cm test`/`cm bench` wrappers
   around pytest/go test/bench_*; PowerShell completions; PowerShell
   profile install step inside `cm setup`.
3. **Part 5**: metrics aggregation from gateway logs + `off/*/decisions.jsonl`
   into `cm status` (error rate, spend vs caps, last scan/test); alerts
   with dedupe; dashboard drill-down wiring in studio; `cm explain <req>`
   joining gateway trace to Drex decision by request id.
4. **Part 6**: GitHub Actions CI (windows+linux) doing fmt/vet/staticcheck,
   pytest, go test, vitest, secret_scan.py, doc-command validation;
   pre-commit hook; coverage report.
5. **E2E mission** (big): extend `scripts/e2e_claude_matrix.py` to the
   full Part-2 scenario matrix with N=5 reps, PTY driver for interactive
   scenarios, independent oracles (fixture tests, git state, MCP logs),
   spend caps, per-commit result storage. Mid-session failover/429/
   budget-stop tests come first among the residency scenarios.
6. **Optimization passes** (Part 3) only behind measured regressions:
   profile first; existing budgets in docs/benchmarks.md are the bar.

## Gotchas learned (do not re-hunt)

- PS 5.1: no `$x = if ...`; argument-mode needs `($hash.key)`; no
  non-ASCII chars in BOM-less ps1 (em dash -> byte 0x94 -> curly-quote
  string delimiter -> swallows the rest of the file).
- `start.ps1` blocks while babysitting children: run it via BACKGROUND
  process or `cm start` from an interactive shell, not a SYNC wrapper.
- Runtime tooling writes live outputs into repo root (`off/`, temp
  logs); all ignored now. `docs/decisions.md` is ADR-only since ADR-008.
