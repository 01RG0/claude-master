# Cleanup Baseline (Frozen)

*Recorded 2026-10-13, branch `rewrite`, commit `f1b422b` + in-flight working tree.
Any refactor step must re-run the baseline suite and match or beat these numbers.
Regression = fix or revert, immediately.*

## Frozen test baseline (real output, this machine)

| Suite | Command | Result | Time |
| :--- | :--- | :--- | :--- |
| Python | `python -m pytest -q` | **162 passed** | 60.5 s |
| Go gateway | `cd gateway && go test -count=1 ./...` | **ok** | 0.61 s |
| Go hookshim | `cd hookshim && go test -count=1 ./...` | **ok** | 1.60 s |
| Go watchdog | `cd watchdog && go test -count=1 ./...` | **ok** | 0.65 s |
| TypeScript | `cd studio && npm test` | **17 passed (5 files)** | 1.43 s |

## Frozen metrics

| Metric | Value |
| :--- | :--- |
| Tracked files | 213 |
| Go LOC (gateway+hookshim+watchdog) | 9,071 |
| Python LOC (brain+scripts+tests) | 10,238 |
| gateway.exe binary | 11,717,632 bytes (~11.2 MB) |
| provider.exe binary | 10,566,656 bytes (~10.1 MB) |
| Working-tree state at freeze | see below |

## Working-tree state at freeze (in-flight work, classified)

Kept (coherent, tested feature — model validation against live provider lists):
- `gateway/probe.go` (+`ValidateModels`), `gateway/cmd/provider/main.go` (live check),
  `gateway/validate_test.go` (3-dialect list parsing: OpenAI/Cohere/Gemini shapes),
  `gateway/config.json` + `gateway/capabilities.json` (retired model fixes,
  detected 2026-10-13: `command-r-plus` retired 2025-09-15 → dated ids), `scripts/detect_all.py`, `data/*` (detection corpus).

Removed as junk (one-off probes with hardcoded absolute paths, now in `scripts/attic/`, untracked forever):
- `scripts/cohere_{probe,v1,native,models,live,e2e}.py`, `scripts/inspect_models.py`, `scripts/repro_validate.py`
- `cmd/dbgvalidate/` (unreferenced debug main; root `go.mod` is a workspace marker only)

Never-tracked runtime outputs (ignored now): `off/`, `logs/`, `*.exe`, `*.exe~`, `.pytest_cache/`, `*.egg-info`.

## Known issue found during baseline (to fix, not frozen as-is)

- **Runtime Drex decision-log appends into `docs/decisions.md`** (live daemon polluted the
  ADR doc twice on 2026-10-13; `git checkout` used to restore). Decision logs must go to
  `off/`/`logs/` queryable storage, not docs. Fix tracked in Part 5 (observability) work.
