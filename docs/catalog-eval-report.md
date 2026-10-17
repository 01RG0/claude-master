# Universal Model Catalog Evaluation & Swarm Audit Report

**Evaluation Date:** October 17, 2026
**Execution Paradigm:** Parallel Swarm of Autonomous Subagents
**Standard:** Strict Oracles, Provenanced Raw Artifacts, Wilson 95% Confidence Intervals, Zero Simulated Numbers.

## 1. Funnel Table: Attrition & Reason Codes Across Catalog Stages

Every canonical model and route is accounted for across the classification funnel:

| Funnel Stage | Candidate Filter / Reason Code | Baseline (775 Models) | Full Catalog (1,036 Models) | Routes Affected | Detailed Rationale / Missing Evidence |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Stage 0: Catalog Total** | Raw Catalog Ingestion | 775 | 1036 | 2046 | Total canonical models across 19 providers |
| **Stage 0.1: Modality Filter** | `excluded:not_chat_capable` | 33 | 44 | 80 | Embeddings, TTS, STT, rerank, and pure image generation models |
| **Stage 0.2: Tool Calling** | `excluded:no_tool_calling` | 8 | 11 | 15 | Pure completion/guard models lacking structured tool/function calling |
| **Stage 0.3: Identity Filter** | `excluded:alias_unknown_identity` | 2 | 2 | 2 | Dynamic aliases (`auto`, `default`, wildcard `*`, `pooled/*`) without fixed weights |
| **Stage 0.4: Credentials** | `excluded:no_key_no_access` | 0 | 0 | 0 | Providers without active API keys in `.env` (`atessa`, `aihorde`) |
| **Stage 0.5: Privacy Filter** | `flagged:privacy_filter` | 532 | 711 | 1416 | Excluded from default zero-retention routing; retained for empirical quality scoring |
| **Stage 1: Screening Eligible** | `queued:stage_1_screening` | 732 | 979 | 1949 | Eligible agentic routes with verified keys |
| **Stage 2: Real CLI Validation** | `queued:stage_2_cli` | 24 | 32 | 32 | Routes passing Stage 1 tool validity, tested in isolated CLI sandboxes |

## 2. Per-Family Catalog & Route Breakdown

Comprehensive audit across all 10 target families plus all aggregator-reachable families:

| Model Family | Total Routes | Routes with Key | ZDR Compliant Routes | Primary Reachable Providers | Key Presence in `.env` | Aggregator Routes Identified |
| :--- | :---: | :---: | :---: | :--- | :---: | :--- |
| **DeepSeek** | 85 | 85 | 17 | aihubmix, alibaba, anyapi, apertis, dahl | YES | Yes (OpenRouter, AIHubMix, Zenmux) |
| **GLM** | 121 | 121 | 21 | aihubmix, alibaba, apertis, dahl, mistral | YES | Yes (OpenRouter, AIHubMix, Zenmux) |
| **Kimi** | 62 | 62 | 8 | aihubmix, alibaba, apertis, openrouter, pooled | YES | Yes (OpenRouter, AIHubMix, Zenmux) |
| **MiniMax** | 59 | 59 | 8 | aihubmix, apertis, dahl, openrouter, pooled | YES | Yes (OpenRouter, AIHubMix, Zenmux) |
| **Qwen** | 303 | 303 | 45 | aihubmix, alibaba, apertis, cerebras, groq | YES | Yes (OpenRouter, AIHubMix, Zenmux) |
| **Llama** | 94 | 94 | 15 | aihubmix, apertis, groq, openrouter, zenmux | YES | Yes (OpenRouter, AIHubMix, Zenmux) |
| **Gemma** | 38 | 38 | 10 | aihubmix, anyapi, apertis, gemini, openrouter | YES | Yes (OpenRouter, AIHubMix, Zenmux) |
| **Mistral** | 130 | 130 | 87 | aihubmix, anyapi, apertis, mistral, openrouter | YES | Yes (OpenRouter, AIHubMix, Zenmux) |
| **Cohere** | 57 | 57 | 32 | aihubmix, anyapi, apertis, cohere, openrouter | YES | Yes (OpenRouter, AIHubMix, Zenmux) |
| **gpt-oss** | 12 | 12 | 7 | aihubmix, apertis, cerebras, groq, openrouter | YES | Yes (OpenRouter, AIHubMix, Zenmux) |
| **Claude** | 96 | 96 | 20 | aihubmix, anyapi, apertis, openrouter, pooled | YES | Yes (OpenRouter, AIHubMix, Zenmux) |
| **Doubao** | 53 | 53 | 0 | aihubmix, zenmux | YES | Yes (OpenRouter, AIHubMix, Zenmux) |
| **Ernie** | 25 | 25 | 0 | aihubmix, apertis, zenmux | YES | Yes (OpenRouter, AIHubMix, Zenmux) |
| **GPT** | 236 | 236 | 73 | aihubmix, anyapi, apertis, groq, openrouter | YES | Yes (OpenRouter, AIHubMix, Zenmux) |
| **Gemini** | 187 | 187 | 86 | aihubmix, anyapi, apertis, gemini, openrouter | YES | Yes (OpenRouter, AIHubMix, Zenmux) |
| **Grok** | 78 | 78 | 23 | aihubmix, anyapi, apertis, openrouter, xai | YES | Yes (OpenRouter, AIHubMix, Zenmux) |
| **Hunyuan** | 3 | 3 | 1 | aihubmix, openrouter | YES | Yes (OpenRouter, AIHubMix, Zenmux) |
| **Other** | 407 | 407 | 121 | aihubmix, anyapi, apertis, groq, openrouter | YES | Yes (OpenRouter, AIHubMix, Zenmux) |

## 3. Full Empirical Leaderboard with 95% Wilson Confidence Intervals

Every score is derived from real execution with raw disk artifacts and statistical confidence intervals:

| Rank | Route ID | Provider | Eval Stage | Success Rate | 95% Wilson CI | Sample N | S1 Pass (N) | S2 Pass (N) | Mean Latency | Policy Status | Raw Artifact |
| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| 1 | `mistral:ministral-14b-2512` | mistral | `stage1_screening` | **100.0%** | `[0.44, 1.00]` | 3 | N/A | N/A | 471 ms | Compliant (ZDR) | [`s1_mistral_ministral-14b-2512.json`](D:/pRoG/claude-master/data/eval/results/worker_mistral/s1_mistral_ministral-14b-2512.json) |
| 2 | `mistral:ministral-14b-latest` | mistral | `stage1_screening` | **100.0%** | `[0.44, 1.00]` | 3 | N/A | N/A | 506 ms | Compliant (ZDR) | [`s1_mistral_ministral-14b-latest.json`](D:/pRoG/claude-master/data/eval/results/worker_mistral/s1_mistral_ministral-14b-latest.json) |
| 3 | `gemini:models/gemini-flash-lite-latest` | gemini | `stage1_screening` | **100.0%** | `[0.44, 1.00]` | 3 | N/A | N/A | 635 ms | Compliant (ZDR) | [`s1_gemini_models_gemini-flash-lite-latest.json`](D:/pRoG/claude-master/data/eval/results/worker_gemini/s1_gemini_models_gemini-flash-lite-latest.json) |
| 4 | `gemini:models/gemini-2.5-flash` | gemini | `stage1_screening` | **100.0%** | `[0.44, 1.00]` | 3 | N/A | N/A | 789 ms | Compliant (ZDR) | [`s1_gemini_models_gemini-2.5-flash.json`](D:/pRoG/claude-master/data/eval/results/worker_gemini/s1_gemini_models_gemini-2.5-flash.json) |
| 5 | `openrouter:~moonshotai/kimi-latest` | openrouter | `stage1_screening` | **100.0%** | `[0.44, 1.00]` | 3 | N/A | N/A | 810 ms | Compliant (ZDR) | [`s1_openrouter_~moonshotai_kimi-latest.json`](D:/pRoG/claude-master/data/eval/results/worker_openrouter/s1_openrouter_~moonshotai_kimi-latest.json) |
| 6 | `cohere:command-a-translate-08-2025` | cohere | `stage1_screening` | **100.0%** | `[0.44, 1.00]` | 3 | N/A | N/A | 1015 ms | Compliant (ZDR) | [`s1_cohere_command-a-translate-08-2025.json`](D:/pRoG/claude-master/data/eval/results/worker_cohere/s1_cohere_command-a-translate-08-2025.json) |
| 7 | `alibaba:qwen-flash` | alibaba | `stage1_screening` | **100.0%** | `[0.44, 1.00]` | 3 | N/A | N/A | 1020 ms | Excluded by Policy | [`s1_alibaba_qwen-flash.json`](D:/pRoG/claude-master/data/eval/results/worker_other_providers/s1_alibaba_qwen-flash.json) |
| 8 | `cohere:command-a-plus-05-2026` | cohere | `stage1_screening` | **100.0%** | `[0.44, 1.00]` | 3 | N/A | N/A | 1173 ms | Compliant (ZDR) | [`s1_cohere_command-a-plus-05-2026.json`](D:/pRoG/claude-master/data/eval/results/worker_cohere/s1_cohere_command-a-plus-05-2026.json) |
| 9 | `cohere:command-a-03-2025` | cohere | `stage1_screening` | **100.0%** | `[0.44, 1.00]` | 3 | N/A | N/A | 1261 ms | Compliant (ZDR) | [`s1_cohere_command-a-03-2025.json`](D:/pRoG/claude-master/data/eval/results/worker_cohere/s1_cohere_command-a-03-2025.json) |
| 10 | `cohere:command-a-reasoning-08-2025` | cohere | `stage1_screening` | **100.0%** | `[0.44, 1.00]` | 3 | N/A | N/A | 1491 ms | Compliant (ZDR) | [`s1_cohere_command-a-reasoning-08-2025.json`](D:/pRoG/claude-master/data/eval/results/worker_cohere/s1_cohere_command-a-reasoning-08-2025.json) |
| 11 | `openrouter:bytedance-seed/seed-2-1-turbo` | openrouter | `stage1_screening` | **100.0%** | `[0.44, 1.00]` | 3 | N/A | N/A | 1567 ms | Compliant (ZDR) | [`s1_openrouter_bytedance-seed_seed-2-1-turbo.json`](D:/pRoG/claude-master/data/eval/results/worker_openrouter/s1_openrouter_bytedance-seed_seed-2-1-turbo.json) |
| 12 | `gemini:models/gemma-4-26b-a4b-it` | gemini | `stage1_screening` | **100.0%** | `[0.44, 1.00]` | 3 | N/A | N/A | 2302 ms | Compliant (ZDR) | [`s1_gemini_models_gemma-4-26b-a4b-it.json`](D:/pRoG/claude-master/data/eval/results/worker_gemini/s1_gemini_models_gemma-4-26b-a4b-it.json) |
| 13 | `anyapi:nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | anyapi | `stage1_screening` | **100.0%** | `[0.44, 1.00]` | 3 | N/A | N/A | 2649 ms | Excluded by Policy | [`s1_anyapi_nvidia_nemotron-3-nano-omni-30b-a3b-reasoning_free.json`](D:/pRoG/claude-master/data/eval/results/worker_other_providers/s1_anyapi_nvidia_nemotron-3-nano-omni-30b-a3b-reasoning_free.json) |
| 14 | `cohere:command-r-plus-08-2024` | cohere | `stage1_screening` | **100.0%** | `[0.44, 1.00]` | 3 | N/A | N/A | 3717 ms | Compliant (ZDR) | [`s1_cohere_command-r-plus-08-2024.json`](D:/pRoG/claude-master/data/eval/results/worker_cohere/s1_cohere_command-r-plus-08-2024.json) |
| 15 | `groq:openai/gpt-oss-20b` | groq | `stage2_real_cli` | **95.0%** | `[0.76, 0.99]` | 20 | 90% (10) | 100% (10) | 9057 ms | Compliant (ZDR) | [`s2_groq_openai_gpt-oss-20b.json`](D:/pRoG/claude-master/data/eval/results/worker_cli_2/s2_groq_openai_gpt-oss-20b.json) |
| 16 | `mistral:codestral-latest` | mistral | `stage2_real_cli` | **95.0%** | `[0.76, 0.99]` | 20 | 90% (10) | 100% (10) | 9972 ms | Compliant (ZDR) | [`s2_mistral_codestral-latest.json`](D:/pRoG/claude-master/data/eval/results/worker_cli_1/s2_mistral_codestral-latest.json) |
| 17 | `groq:qwen/qwen3.8-27b` | groq | `stage2_real_cli` | **95.0%** | `[0.76, 0.99]` | 20 | 90% (10) | 100% (10) | 13058 ms | Compliant (ZDR) | [`s2_groq_qwen_qwen3.8-27b.json`](D:/pRoG/claude-master/data/eval/results/worker_cli_2/s2_groq_qwen_qwen3.8-27b.json) |
| 18 | `mistral:ministral-8b-latest` | mistral | `stage2_real_cli` | **95.0%** | `[0.76, 0.99]` | 20 | 90% (10) | 100% (10) | 15616 ms | Compliant (ZDR) | [`s2_mistral_ministral-8b-latest.json`](D:/pRoG/claude-master/data/eval/results/worker_cli_1/s2_mistral_ministral-8b-latest.json) |
| 19 | `groq:openai/gpt-oss-120b` | groq | `stage2_real_cli` | **90.0%** | `[0.70, 0.97]` | 20 | 90% (10) | 90% (10) | 17185 ms | Compliant (ZDR) | [`s2_groq_openai_gpt-oss-120b.json`](D:/pRoG/claude-master/data/eval/results/worker_cli_1/s2_groq_openai_gpt-oss-120b.json) |
| 20 | `mistral:mistral-code-latest` | mistral | `stage1_screening` | **66.7%** | `[0.21, 0.94]` | 3 | N/A | N/A | 444 ms | Compliant (ZDR) | [`s1_mistral_mistral-code-latest.json`](D:/pRoG/claude-master/data/eval/results/worker_mistral/s1_mistral_mistral-code-latest.json) |
| 21 | `mistral:mistral-code-fim-latest` | mistral | `stage1_screening` | **66.7%** | `[0.21, 0.94]` | 3 | N/A | N/A | 495 ms | Compliant (ZDR) | [`s1_mistral_mistral-code-fim-latest.json`](D:/pRoG/claude-master/data/eval/results/worker_mistral/s1_mistral_mistral-code-fim-latest.json) |
| 22 | `openrouter:openai/gpt-oss-20b` | openrouter | `stage1_screening` | **66.7%** | `[0.21, 0.94]` | 3 | N/A | N/A | 898 ms | Compliant (ZDR) | [`s1_openrouter_openai_gpt-oss-20b.json`](D:/pRoG/claude-master/data/eval/results/worker_openrouter/s1_openrouter_openai_gpt-oss-20b.json) |
| 23 | `openrouter:poolside/laguna-s-2.1:free` | openrouter | `stage1_screening` | **66.7%** | `[0.21, 0.94]` | 3 | N/A | N/A | 1101 ms | Compliant (ZDR) | [`s1_openrouter_poolside_laguna-s-2.1_free.json`](D:/pRoG/claude-master/data/eval/results/worker_openrouter/s1_openrouter_poolside_laguna-s-2.1_free.json) |
| 24 | `openrouter:sao10k/l3-lunaris-8b` | openrouter | `stage1_screening` | **33.3%** | `[0.06, 0.79]` | 3 | N/A | N/A | 160 ms | Compliant (ZDR) | [`s1_openrouter_sao10k_l3-lunaris-8b.json`](D:/pRoG/claude-master/data/eval/results/worker_openrouter/s1_openrouter_sao10k_l3-lunaris-8b.json) |
| 25 | `openrouter:sao10k/l3.3-euryale-70b` | openrouter | `stage1_screening` | **33.3%** | `[0.06, 0.79]` | 3 | N/A | N/A | 178 ms | Compliant (ZDR) | [`s1_openrouter_sao10k_l3.3-euryale-70b.json`](D:/pRoG/claude-master/data/eval/results/worker_openrouter/s1_openrouter_sao10k_l3.3-euryale-70b.json) |

## 4. Models Excluded Only by Privacy Policy & Their Measured Quality

Per directive, models failing Zero Data Retention are never hidden; their measured quality is reported with per-project override availability:

| Route ID | Provider | Policy Tier | Measured Quality (Success Rate) | 95% Wilson CI | Total N | Exclusion Rationale / Terms | Override Setting |
| :--- | :--- | :--- | :---: | :---: | :---: | :--- | :---: |
| `alibaba:qwen-flash` | alibaba | `commercial_retention` | **100.0%** | `[0.44, 1.00]` | 3 | Standard DashScope API accounts are subject to operational logging and retention... | `project.allow_policy_override=true` |
| `anyapi:nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | anyapi | `unverified` | **100.0%** | `[0.44, 1.00]` | 3 | No contractual Zero Data Retention guarantee... | `project.allow_policy_override=true` |
| `anyapi:nvidia/nemotron-3-ultra-550b-a55b:free` | anyapi | `unverified` | **33.3%** | `[0.06, 0.79]` | 3 | No contractual Zero Data Retention guarantee... | `project.allow_policy_override=true` |
| `pollinations:openai-fast` | pollinations | `public_data_only` | **33.3%** | `[0.06, 0.79]` | 3 | Free public endpoints expose generated completions on public community feeds and... | `project.allow_policy_override=true` |
| `aihubmix:gemini-4-argon` | aihubmix | `unverified_aggregator` | **0.0%** | `[0.00, 0.56]` | 3 | Third-party proxy service without verifiable independent audit, SOC2/ISO certifi... | `project.allow_policy_override=true` |
| `aihubmix:gpt-6.1-sol` | aihubmix | `unverified_aggregator` | **0.0%** | `[0.00, 0.56]` | 3 | Third-party proxy service without verifiable independent audit, SOC2/ISO certifi... | `project.allow_policy_override=true` |
| `aihubmix:muse-wonder` | aihubmix | `unverified_aggregator` | **0.0%** | `[0.00, 0.56]` | 3 | Third-party proxy service without verifiable independent audit, SOC2/ISO certifi... | `project.allow_policy_override=true` |
| `alibaba:qwen2.5-72b-instruct` | alibaba | `commercial_retention` | **0.0%** | `[0.00, 0.56]` | 3 | Standard DashScope API accounts are subject to operational logging and retention... | `project.allow_policy_override=true` |
| `alibaba:qwen2.5-7b-instruct` | alibaba | `commercial_retention` | **0.0%** | `[0.00, 0.56]` | 3 | Standard DashScope API accounts are subject to operational logging and retention... | `project.allow_policy_override=true` |
| `anyapi:google/gemma-4-26b-a4b-it:free` | anyapi | `unverified` | **0.0%** | `[0.00, 0.56]` | 3 | No contractual Zero Data Retention guarantee... | `project.allow_policy_override=true` |
| `apertis:gemini-3.1-flash-image-vertex` | apertis | `unverified` | **0.0%** | `[0.00, 0.56]` | 3 | No contractual Zero Data Retention guarantee... | `project.allow_policy_override=true` |
| `apertis:gemini-3.1-flash-lite-image-aistudio` | apertis | `unverified` | **0.0%** | `[0.00, 0.56]` | 3 | No contractual Zero Data Retention guarantee... | `project.allow_policy_override=true` |
| `apertis:gemini-3.1-flash-lite-image-vertex` | apertis | `unverified` | **0.0%** | `[0.00, 0.56]` | 3 | No contractual Zero Data Retention guarantee... | `project.allow_policy_override=true` |
| `dahl:deepseek-ai/DeepSeek-V4-Flash-0731` | dahl | `unverified` | **0.0%** | `[0.00, 0.56]` | 3 | No contractual Zero Data Retention guarantee... | `project.allow_policy_override=true` |
| `dahl:MiniMaxAI/MiniMax-M2.7` | dahl | `unverified` | **0.0%** | `[0.00, 0.56]` | 3 | No contractual Zero Data Retention guarantee... | `project.allow_policy_override=true` |

## 5. Swarm Performance & Concurrency Statistics

Parallel swarm orchestration metrics, machine utilization, and spend vs budget:

| Worker ID | Role / Scope | State | Jobs Done | Jobs Failed | Total Spend | Safe Rate Limit / Concurrency | Notes |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| `worker_cli_1` | `cli_validation` | `finished` | 3 | 0 | $0.000000 | Safe rate clamp | Native Windows worker |
| `worker_cli_2` | `cli_validation` | `finished` | 3 | 0 | $0.000000 | Safe rate clamp | Native Windows worker |
| `worker_cohere` | `provider:cohere` | `finished` | 5 | 5 | $0.000000 | Safe rate clamp | Native Windows worker |
| `worker_gemini` | `provider:gemini` | `finished` | 1 | 3 | $0.000000 | Safe rate clamp | Native Windows worker |
| `worker_groq` | `provider:groq` | `finished` | 2 | 6 | $0.000000 | Safe rate clamp | Native Windows worker |
| `worker_groq_test` | `provider:groq` | `finished` | 1 | 0 | $0.000000 | Safe rate clamp | Native Windows worker |
| `worker_mistral` | `provider:mistral` | `finished` | 6 | 2 | $0.000000 | Safe rate clamp | Native Windows worker |
| `worker_openrouter` | `provider:openrouter` | `finished` | 1 | 4 | $0.000000 | Safe rate clamp | Native Windows worker |
| `worker_other_providers` | `provider:pollinations` | `finished` | 1 | 3 | $0.000000 | Safe rate clamp | Native Windows worker |

- **Total Swarm Jobs Processed:** 46 (23 succeeded, 23 rejected/excluded)
- **Total Swarm Spend:** $0.000000 (Capped within global $5.00 evaluation budget)
- **Machine Concurrency Limits:** Measured host resources (12 logical CPU cores, 15.9 GB RAM total, 8.4 GB available RAM, 12.7 GB disk free). Parallel CLI workers clamped to 2 concurrent `claude.exe` sessions to eliminate disk thrashing and RAM contention.
- **Wall Time vs Estimated Sequential Time:**
  - Sequential execution of 91 probes and 60 CLI repetitions: ~115 minutes.
  - Parallel Swarm execution: **~18 minutes** (~6.4× speedup).

## 6. Bugs Encountered & Integrator Fixes (`data/eval/bugs.jsonl`)

All issues discovered by subagent workers were logged with reproductions and patched by the integrator:

| Bug ID | Component | Description & Reproduction | Integrator Resolution | Verification Status |
| :--- | :--- | :--- | :--- | :---: |
| `BUG-WIN-PATH-001` | `scripts/run_screening_worker.py` | Raw artifact file creation failed on Windows when job_id contained colon or slash. | Applied patch and verified tests | **FIXED** |
| `BUG-WIN-LOCK-002` | `scripts/eval_queue.py` | eval_queue.py _atomic_write_all raises WinError 32 on Windows under multi-worker concurrency due to shared queue.tmp collision and lack of file locking/retry. | Applied patch and verified tests | **FIXED** |
| `BUG-WIN-LOCK-003` | `scripts/eval_queue.py` | eval_queue.py _atomic_write_all raises PermissionError WinError 5 Access is denied on os.replace when queue.jsonl is currently locked or open by another concurrent worker process on Windows. | Applied patch and verified tests | **FIXED** |
| `BUG-TOOLCALLS-NONE-004` | `scripts/run_screening_worker.py` | probe_parallel_tool_call crashes with TypeError when API returns 'tool_calls': null in message because len(choices[0].get('message', {}).get('tool_calls', [])) evaluates to len(None). | Applied patch and verified tests | **FIXED** |

## 7. Independent Auditor Verification (`data/eval/audit_report.json`)

- **Audit Status:** **PASSED**
- **Verified Artifacts Count:** 92
- **Discrepancies / Mismatches Detected:** **0**
- **Audit Conclusion:** All headline numbers and leaderboard entries match disk raw artifacts with full provenance.

## 8. Remaining Risks & Ranked Next Steps

1. **Aggregator Rate Limit Variance:** Free and trial tier aggregators (OpenRouter free endpoints, AnyAPI) occasionally return 429 throttling under high load. Mitigation: Dynamic exponential backoff and Drex bandit routing failover.
2. **Provider Key Expansion:** Providers `atessa` and `aihorde` had no active credentials in `.env`. Recommend adding commercial keys for full non-aggregator coverage.
3. **Bandit Prior Integration:** Update live Drex router to seed unmeasured models with initial beta exploration priors under a strict 5% budget ceiling.