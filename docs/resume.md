# Resume Point (2026-10-17, Catalog Swarm Evaluation Run)

Branch `rewrite`, evaluated across native Windows swarm with strict atomic file leases (`data/eval/queue.jsonl`), per-worker isolated result directories, and independent auditor verification.

## 1. Catalog Scale & Baseline Inventory State
- **Catalog Baseline**: 775 canonical models across 1,878 routes and 19 providers.
- **Extended Ingested Catalog**: 1,036 canonical models across 2,046 routes and 19 providers.
- **Funnel Classification**:
  - Excluded Non-Chat: 44 models / 80 routes (`excluded:not_chat_capable`).
  - Excluded Non-Agentic / No-Tool: 11 models / 15 routes (`excluded:no_tool_calling`).
  - Excluded Aliases / Wildcards: 2 models / 2 routes (`excluded:alias_unknown_identity`).
  - Excluded Missing Keys: 0 routes in catalog (providers `atessa`, `aihorde` unkeyed in `.env`).
  - Excluded / Flagged by Privacy Policy: 711 models / 1,416 routes (`flagged:privacy_filter`).
  - Eligible for Screening: 979 models / 1,949 routes (`queued:stage_1_screening`).
  - Queue Storage: `data/eval/queue.jsonl` (4,092 total jobs, 2,046 per stage).

## 2. Swarm Execution Summary
- **Workers Spawned in Parallel**:
  - Provider Workers: `worker_groq`, `worker_mistral`, `worker_gemini`, `worker_cohere`, `worker_openrouter`, `worker_other_providers`.
  - CLI Workers: `worker_cli_1` (port 18091), `worker_cli_2` (port 18092).
  - Analysis & Audit Workers: `scripts/run_analysis_worker.py`, `scripts/run_auditor_worker.py`.
- **Total Raw Artifacts Stored**: 92 independent JSON response files in `data/eval/results/`.
- **Audit Verification**: 92/92 artifacts verified by auditor with **0 mismatches**. Status: **PASSED**.
- **Real CLI Benchmarks (N=10 to 20 per route, strict S1 & S2 oracles)**:
  - `groq:openai/gpt-oss-120b`: S1 90.0% [0.60, 0.98], S2 90.0% [0.60, 0.98], mean lat 17.2s.
  - `mistral:ministral-8b-latest`: S1 90.0% [0.60, 0.98], S2 100.0% [0.72, 1.00], mean lat 15.6s.
  - `mistral:codestral-latest`: S1 90.0% [0.60, 0.98], S2 100.0% [0.72, 1.00], mean lat 10.0s.
  - `groq:qwen/qwen3.8-27b`: S1 90.0% [0.60, 0.98], S2 100.0% [0.72, 1.00], mean lat 13.1s.
  - `groq:openai/gpt-oss-20b`: S1 90.0% [0.60, 0.98], S2 100.0% [0.72, 1.00], mean lat 9.1s.
  - `mistral:codestral-2508`: S1 20.0% [0.06, 0.51], S2 0.0% [0.00, 0.56] (early stopped due to upstream timeouts).

## 3. Bugs Logged & Fixed (`data/eval/bugs.jsonl`)
- `BUG-WIN-PATH-001`: Windows path separator colon/slash sanitization in artifact paths. (Status: FIXED)
- `BUG-WIN-LOCK-002`: Multi-worker Windows file contention on `queue.tmp` atomic replace. (Status: FIXED via unique PID/timestamp filenames and backoff retry loop)
- `BUG-WIN-LOCK-003`: `PermissionError: [WinError 5]` on concurrent replace. (Status: FIXED)
- `BUG-TOOLCALLS-NONE-004`: `TypeError` on `len(None)` when provider returns `"tool_calls": null`. (Status: FIXED)

## 4. Continuing or Extending the Evaluation
To resume or run additional screening / CLI jobs without repeating finished jobs:
1. All finished jobs remain in `state: done` in `data/eval/queue.jsonl`.
2. To claim the next batch of queued Stage 1 screening jobs:
   ```powershell
   python scripts/run_screening_worker.py --worker-id worker_resumed --provider openrouter --max-jobs 20
   ```
3. To run additional Stage 2 real CLI sessions:
   ```powershell
   python scripts/run_cli_worker.py --worker-id worker_cli_resumed --gateway-port 18095 --reps 10 --max-routes 3
   ```
4. Re-run analysis and audit:
   ```powershell
   python scripts/run_analysis_worker.py; python scripts/run_auditor_worker.py; python scripts/generate_final_report.py
   ```
