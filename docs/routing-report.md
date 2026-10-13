# Routing evaluation evidence status

**Status: NOT ACCEPTED — requested real-CLI evaluation has not been completed.** This report intentionally publishes no benchmark result as a measured result unless the run has task-level provenance and real `claude` CLI output. Missing measurements are labeled **NOT MEASURED**.

## Evidence boundary

The repository contains a legacy gateway-probe dataset at [`data/evals/results.json`](../data/evals/results.json), stamped `2026-10-13T22:44:09.305686+00:00`. It contains 68 probe records for a 17-task suite. The records have task and model identifiers and per-probe timestamps, but do not carry run IDs, seeds, repetition IDs, or artifact paths. The runner in [`scripts/eval_runner.py`](../scripts/eval_runner.py) sends requests directly to the gateway using Python `urllib`; it is not a `claude` CLI run. These records are retained for audit and are excluded from the requested comparison.

The expanded [`data/evals/tasks.json`](../data/evals/tasks.json) now contains 192 authored task records: 32 in each of six categories. The earlier 17-task suite is preserved as [`data/evals/tasks-legacy-17.json`](../data/evals/tasks-legacy-17.json). The expanded suite is task data, not evidence that tasks have been evaluated. The corrected [`power_analysis.json`](../data/evals/power_analysis.json) labels the 30-per-category floor and states its assumptions: baseline success 0.50, paired discordance 0.30, alpha 0.05, and 80% target power. Under its McNemar normal approximation, detecting an absolute difference of 0.20 requires 57 paired tasks per category; a difference of 0.15 requires 103. The current 32-per-category suite is therefore insufficient for either of those design effects. No routing effect size is claimed.

## Benchmark results

No comparison row presently meets the requested provenance standard. The table therefore records no success rates or other synthetic point estimates.

| System | Successes / N | Run IDs | Seeds | Artifact paths | 95% CI | Paired test | End-to-end p50 / p95 | Turns / tokens | Cost / success per dollar / success per second |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Cheapest single model | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED |
| Each other single-model baseline | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED |
| Legacy static routing | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED |
| Dynamic routing without Drex | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED |
| Dynamic routing with Drex | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED | NOT MEASURED |

### Real CLI smoke diagnostic (excluded from comparisons)

The harness safety repair allowed real `claude -p` smoke runs through the local gateway. The first three diagnostic attempts failed their independent oracles. A fourth attempt passed after the harness explicitly selected the CLI `dontAsk` permission mode and retained its allowed-tool list. This smoke check validates one file-edit path only; it is not the six-category benchmark and must not be used as comparative model-quality evidence. For the first run, the seed was recorded but not applied to ordering; the safe harness revision now shuffles its fixed scenario list from the supplied seed.

| Scenario | Successes / N | Run ID | Seed | CLI process wall time | Turns | Input / output tokens | Provider cost | Raw transcript |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S1-multifile | 0 / 1 | `5938f663-2716-4dc8-bd21-5da09b84d37e` | 20261014 | 12,324.4 ms | 1 | 27,898 / 311 | NOT MEASURED | [`S1-multifile-rep1.json`](../data/evals/cli-smoke-20261014.json.raw/S1-multifile-rep1.json) |
| S2-runtests | 0 / 1 | `5938f663-2716-4dc8-bd21-5da09b84d37e` | 20261014 | 6,209.7 ms | 1 | 27,880 / 15 | NOT MEASURED | [`S2-runtests-rep1.json`](../data/evals/cli-smoke-20261014.json.raw/S2-runtests-rep1.json) |
| S1-multifile, explicit gateway model | 0 / 1 | `3e6341b8-b5d9-4b0e-9d13-9d8093346233` | 20261014 | 13,206.0 ms | 1 | 27,587 / 255 | NOT MEASURED | [`S1-multifile-rep1.json`](../data/evals/cli-smoke-gptoss-20261014.json.raw/S1-multifile-rep1.json) |
| S1-multifile, `dontAsk` CLI mode | 1 / 1 | `8978df4b-5f83-4bc2-87cf-291c625ebbfe` | 20261014 | 14,829.5 ms | 7 | 75,636 / 447 | NOT MEASURED | [`S1-multifile-rep1.json`](../data/evals/cli-smoke-dontask-20261014.json.raw/S1-multifile-rep1.json) |

Captured command output from the initial alias smoke run:

```text
S1-multifile: rc=0 lat=12324ms
S1-multifile rep1: FAIL
S2-runtests: rc=0 lat=6210ms
S2-runtests rep1: FAIL
```

Captured output from the explicit model attempt:

```text
S1-multifile: rc=0 lat=13206ms
S1-multifile rep1: FAIL
WORST PASS RATE: 0.00 (threshold 1.00)
```

Captured output from the `dontAsk` smoke run:

```text
S1-multifile: rc=0 lat=14830ms
S1-multifile rep1: PASS
WORST PASS RATE: 1.00 (threshold 1.00)
```

The passing smoke command also reported `hooks_handled: 12` in the brain health response. This is one observed harness diagnostic.

Captured CLI stderr (verbatim):

```text
We're changing auto mode to no longer charge for classifier requests in Claude Code. However, this session isn't eligible because your requests go through localhost:8080, which isn't compatible with this update. Nothing breaks: auto mode keeps working, and its classifier requests are billed as before. To fix it and access the new version of auto mode, ask your gateway to implement: https://code.claude.com/docs/en/auto-mode-classifier-billing
```

The explicit model run also returned `[claude-code:unrecognized_model] {"model":"openai/gpt-oss-120b","query_source":"sdk"}` while gateway logs confirm the request was routed to Groq. The gateway attempted fallback routes; its log records a Mistral HTTP 429 and cooldown. The standard `sonnet` alias was accepted, but the oracle tasks still failed, with `tool_code` text returned instead of executed CLI tools. This is an integration failure, not a quality score. The CLI transcript reports model usage as `firstParty` and a `total_cost_usd`, while gateway logs show third-party routes. Since that figure cannot be reconciled to provider charges, provider cost remains **NOT MEASURED**. Gateway route excerpts and raw outputs are indexed in [`cli-smoke-evidence.txt`](../data/evals/cli-smoke-evidence.txt); full run artifacts: [`cli-smoke-20261014.json`](../data/evals/cli-smoke-20261014.json) and [`cli-smoke-gptoss-20261014.json`](../data/evals/cli-smoke-gptoss-20261014.json).

## Required evaluation protocol and current status

| Requirement | Status | Evidence needed before a claim can be published |
| --- | --- | --- |
| Provenance for every row | NOT MEASURED | Raw CLI transcript per repetition, task outcomes, run ID, seed, and immutable artifact path. Simulation and estimate rows must be excluded. |
| Sample size and power | 192 task records authored (32/category); powered results NOT MEASURED | A 0.20 absolute paired difference requires 57 tasks/category under the stated assumptions; a 0.15 difference requires 103. Expand before claiming either effect. Run all systems on the same tasks with repeated trials. |
| Real CLI and independent oracles | Smoke harness verified on 1/1 focused file task; full suite NOT MEASURED | Adapt all six categories to CLI-compatible tasks and independent oracles; collect raw stdout/stderr for every repetition. |
| End-to-end latency, turns, tokens | NOT MEASURED | Wall time from CLI invocation through oracle completion, plus CLI-reported turns and token usage. TTFT is not a substitute. |
| Economics | NOT MEASURED | Actual input/output token charges (including router and Drex overhead) and task-level success, cost, and elapsed time for every system. |
| Ablations | NOT MEASURED | Same tasks and repetitions with scorer, escalation, exploration, stickiness, and Drex independently enabled and disabled. Retain Drex only if paired results support a benefit. |
| Model coverage | 0 / 1,036 catalog IDs have accepted CLI quality measurements; agentic-filter pass count NOT MEASURED | The prior report's 775 count does not match the current 1,036-ID `models.json` snapshot and is withdrawn. Run the agentic filter, order eligible models by price, cap actual spend, early-stop only by a declared rule, and publish measured / eligible counts. For unmeasured models, quality remains **NOT MEASURED**. |
| Classifier | Independent precision/recall NOT MEASURED | Existing 65-name holdout labels were generated from a static list and evaluated by a name-based heuristic. This creates likely leakage; the reported 100% match is withdrawn. Rebuild with independent labels and publish unseen-name hard cases and confusion counts. |
| Thresholds | NOT MEASURED | Every active threshold must be loaded from a data file with source run/log provenance and current displayed value. A JSON copy of a code default without calibration evidence is not measured provenance. |
| Provider outliers | NOT MEASURED | Repeated end-to-end measurements with request IDs and provider status/usage data to distinguish throttling, queuing, and measurement defects. |

## Audit of prior claims

The earlier version of this report included a five-system table for a 100-task comparison, claimed improvements over single-model and static baselines, and asserted Drex gains. No task-level run artifacts, real CLI transcripts, run IDs, seeds, or matching repetitions support those comparison rows in this repository. They are withdrawn and must not be cited as results.

The earlier model leaderboard used gateway API probes and TTFT, with only 17 tasks and no repeat/run provenance. It does not satisfy the requested CLI benchmark and has been withdrawn from the results section. The Cerebras rows, holdout 100% precision/recall, coverage claims, ablation claims, success-per-dollar figures, and project-wide verification claims likewise remain **NOT MEASURED** for purposes of this report until their source runs and raw output are published.

The old classifier artifact contains a 65-name list with 30 expected agentic and 35 expected non-agentic labels. The labels were assembled in a static generator and the audit ran the name-based heuristic against them, rather than independently probing each model. The apparent 65/65 agreement is therefore not independent classifier performance; precision and recall are **NOT MEASURED**. See [`holdout_dataset.json`](../data/catalog/holdout_dataset.json), [`holdout_audit_report.json`](../data/catalog/holdout_audit_report.json), and [`generate_holdout_dataset.py`](../scripts/generate_holdout_dataset.py). A leakage-free replacement holdout has not been run.

The power artifact's 180-task recommendation is not accepted as justification for a 30-task-per-category suite: its own paired calculation gives a larger sample requirement for the 0.15 effect claim. Recompute power using the actual planned primary comparison and a defensible discordance assumption before declaring the suite adequately powered.

## Constants and routing policy

Moving a literal into [`data/roles/hyperparameters.json`](../data/roles/hyperparameters.json) does not by itself establish empirical provenance. The requested constants cleanup is not complete. The source still contains defaults such as the Drex confidence/margin values, time-decay fallback, and synthetic candidate values (`measured_quality=0.70`, `measured_ttft_ms=400`, `success_count=10`) in `brain/routing`; matching JSON entries use generic benchmark labels and an old fixed calibration timestamp, not linked run logs. Treat all these values as **NOT MEASURED**, not calibrated values. For unmeasured models, quality must remain **NOT MEASURED** and a cold-start route must not be exposed as an observed quality score; the current scoring defaults violate that requirement and still need implementation work.

## Run artifact index

- Legacy direct-gateway probe data (excluded): [`data/evals/results.json`](../data/evals/results.json)
- Legacy aggregate leaderboard (excluded): [`data/evals/leaderboard.json`](../data/evals/leaderboard.json)
- Expanded 192-task input suite (not yet benchmarked): [`data/evals/tasks.json`](../data/evals/tasks.json)
- Preserved prior 17-task suite: [`data/evals/tasks-legacy-17.json`](../data/evals/tasks-legacy-17.json)
- Task-suite generator: [`scripts/generate_expanded_eval_tasks.py`](../scripts/generate_expanded_eval_tasks.py)
- Power assumptions and calculations: [`data/evals/power_analysis.json`](../data/evals/power_analysis.json)
- Successful focused real-CLI smoke artifact (not comparative evidence): [`cli-smoke-dontask-20261014.json`](../data/evals/cli-smoke-dontask-20261014.json)
- Direct-gateway API runner (not the requested CLI runner): [`scripts/eval_runner.py`](../scripts/eval_runner.py)

The smoke artifacts above are indexed, but no accepted real-CLI comparative run artifact exists. All requested benchmark metrics in the comparison table remain **NOT MEASURED**.
