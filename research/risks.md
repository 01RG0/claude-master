# Risk Assessment: Licenses, Dead Projects, Provider Limits, and Architectural Gaps

This report audits the critical operational, legal, and systemic risks associated with building an autonomous neuro-inspired brain system around Claude Code, along with concrete mitigation strategies for each risk.

---

## 1. Licensing & Legal Compliance Audit

Every candidate repository across the 7 tracks was audited for license terms. Several key projects carry viral copyleft or non-standard restrictions that must be quarantined.

| Repository | Detected License | Risk Level | Nature of Risk | Architectural Mitigation Strategy |
| :--- | :--- | :---: | :--- | :--- |
| **`jakdot/pyactr`** | **GPL-3.0** | **HIGH** | Viral copyleft. Incorporating code or linking as a library would legally compel the entire brain system to be licensed under GPL-3.0. | **Clean-Room Algorithmic Port**: Do not import or copy code. Implement the public mathematical equations for base-level learning and activation spreading from academic literature in pure Python/Go. |
| **`free-claude-code`** (`fcc`) | **AGPL-3.0** | **CRITICAL** | Affero GPL requires network-triggered disclosure of full source code for any derivative service or combined program. | **Zero-Code Quarantine**: Absolutely zero code from `fcc` will be copied or imported. We only utilize the documented standard environment variable redirection (`ANTHROPIC_BASE_URL`) supported natively by Anthropic's Claude Code CLI. |
| **`QuantumNous/new-api`** | **AGPL-3.0** | **CRITICAL** | The popular fork of `one-api` transitioned to AGPL-3.0, restricting server-side modifications. | **Drop Repository**: Do not adopt `new-api`. Use our own lightweight in-process Python `AdaptiveCooldownCache` ported from MIT-licensed `litellm`. |
| **`songquanpeng/one-api`** | **Custom MIT + Attribution** | **MEDIUM** | Non-standard MIT modification requiring visible public website links/credits for any derivative work. | **Drop Repository**: Avoid unnecessary legal ambiguity. The channel routing algorithm is simple to implement independently in ~100 lines of standard Python. |
| **`BerriAI/litellm`** | **MIT (Root: NOASSERTION)** | **LOW** | Root repository is flagged `NOASSERTION` on GitHub because an `enterprise/` subfolder contains proprietary add-ons. Core router is MIT. | **Selective Extraction**: Extract only the standalone MIT-licensed `CooldownCache` and `lowest_tpm_rpm_v2.py` files from the open-source core. Avoid `enterprise/`. |
| **`jacomyal/sigma.js`** | **MIT** | **NONE** | Permissive MIT. Unencumbered. | Direct modular adoption of GLSL shader programs and FA2 layout supervisor. |
| **`asg017/sqlite-vec`** | **Apache-2.0** | **NONE** | Permissive Apache-2.0. Unencumbered. | Dynamic C-extension loading via standard SQLite interface. |
| **`open-spaced-repetition/py-fsrs`** | **MIT** | **NONE** | Permissive MIT. Unencumbered. | Direct adoption of mathematical FSRS-5 scheduling formulas. |
| **`getzep/graphiti`** | **Apache-2.0** | **NONE** | Permissive Apache-2.0. Unencumbered. | Port bi-temporal edge data model to SQLite relational schema. |

---

## 2. Stale, Dead, or Research-Only Codebases

Several foundational papers in the agent memory and reflection space provide codebases that are unmaintained research artifacts rather than production-ready libraries:

| System | Maintenance Status | Danger of Direct Dependency | Mitigation Strategy |
| :--- | :--- | :--- | :--- |
| **`noahshinn/reflexion`** | **Stale Research Artifact** (Last commit: Jan 2025; NeurIPS 2023) | Monolithic Python scripts with hardcoded benchmark environments (HotpotQA, HumanEval) and deprecated OpenAI SDK v0.28 calls. | **Extract Pattern, Drop Package**: Extract only the core verbal reflection prompt template (`PY_SELF_REFLECTION_CHAT_INSTRUCTION`) and the generic 40-line `run_reflexion` execution loop into our own clean harness. |
| **`madaan/self-refine`** | **Dead Academic Artifact** (Last commit: late 2023) | Rigid task-specific scripts, unmaintained dependency pins, lack of modern streaming or tool-call support. | **Adopt Philosophy Only**: Implement the decoupled 3-phase loop (`init -> feedback -> iterate`) natively within Claude Code's hook lifecycle. |
| **`ml-jku/hopfield-layers`** | **Inactive** (Last commit: Jan 2022) | Heavy PyTorch GPU tensor dependencies designed for transformer attention layers rather than symbolic agent memory. | **Drop**: Modern DiskANN (`sqlite-vec`) and FSRS-5 associative power-law graphs completely supersede dense Hopfield matrices for symbol retrieval. |
| **`OpenHands/software-agent-sdk`** | **Active Monorepo** (SDK: ~1.2k stars, Core: 89k+) | Pulling in the entire OpenHands framework introduces hundreds of transitives (Docker daemons, FastAPI servers, Jupyter kernels). | **Surgical File Extraction**: Extract strictly `openhands/sdk/conversation/stuck_detector.py` (~370 LOC) which is self-contained and has zero external dependencies beyond standard Python collections. |

---

## 3. Free-Tier Provider Limits, Quotas & Terms-of-Service (TOS) Risks

Operating a 100% free multi-provider routing substrate introduces serious operational constraints and terms-of-service risks:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        CRITICAL FREE-TIER PROVIDER CONSTRAINTS                         │
├─────────────┬─────────────┬─────────────┬─────────────┬────────────────────────────────┤
│ Provider    │ RPM Limit   │ TPM Limit   │ Daily Limit │ Primary Risk / Constraint      │
├─────────────┼─────────────┼─────────────┼─────────────┼────────────────────────────────┤
│ Cerebras    │ 30 RPM      │ 60,000 TPM  │ 1M tok/day  │ 8k context cap; 429 burst spike│
│ Groq        │ 30 RPM      │ 6,000 TPM   │ Org shared  │ Very low TPM on large prompts  │
│ Gemini Free │ 15 RPM      │ 1,000,000   │ 1,500 RPD   │ PRIVACY VIOLATION: Human review│
│ Mistral     │ ~30 RPM     │ N/A         │ Tier 0 test │ Requires SMS phone verification│
│ Cohere      │ 20 RPM      │ N/A         │ 1k req/month│ Hard monthly cap (Rerank only) │
│ GitHub Mod. │ 15 RPM      │ 150 RPD     │ Interactive │ ACCOUNT SUSPENSION on botting  │
└─────────────┴─────────────┴─────────────┴─────────────┴────────────────────────────────┘
```

### 3.1 The Google Gemini Free-Tier Privacy Threat
> [!CAUTION]
> **CRITICAL DATA PRIVACY RISK**: Google AI Studio terms state that data sent to the free-tier API is **logged, reviewed by human contractors, and used to train Google's commercial models**.
> 
> **Enforced Architecture Rule**: NEVER send proprietary source code, credentials, `.env` files, or confidential repository diffs to Google Gemini free tier. Gemini free tier may ONLY be used for synthetic benchmarks, public open-source analysis, or general programming theory questions. All sensitive repository queries must route to zero-retention providers (Groq, Cerebras) or local models.

### 3.2 The GitHub Models Account Suspension Threat
> [!WARNING]
> GitHub Models provides free token quotas for developer prototyping. However, GitHub's Acceptable Use Policy (AUP) explicitly prohibits automated botting, multi-key rotation pools, or using free developer personal access tokens to power background production daemons. Violations can result in the **immediate and permanent suspension of the developer's primary GitHub account**.
> 
> **Enforced Architecture Rule**: Do NOT create automated multi-account rotation pools against GitHub Models. Restrict GitHub Models strictly to single-developer interactive fallback when all other providers are exhausted.

### 3.3 Mitigating Groq / Cerebras 429 Bursts
- **The Issue**: Agentic coding loops execute multiple tool calls in rapid succession. A 30 RPM limit will be exhausted in under 30 seconds of intensive refactoring.
- **The Fix**:
  1. **Prompt Caching**: Structure prompts so system instructions and static conventions are identical prefixes across requests, maximizing provider prompt cache hits.
  2. **Multi-Key Cooldown Cascades**: Use 2–3 keys per provider, rotating on a round-robin schedule and placing keys in a 60-second cooldown immediately upon receiving an HTTP 429.
  3. **Hierarchical Task Offloading**: Run low-complexity operations (format checks, syntax checks) through Cerebras (2000 tok/s), reserving frontier models strictly for complex reasoning.

---

## 4. Gaps in the Open-Source Ecosystem & Our Novel Solutions

No single existing framework solves the entire problem of an autonomous, neuro-inspired, self-healing memory system for coding agents. Our architecture closes three fundamental industry gaps:

### Gap 1: Continuous Neuro-Synaptic Weights vs. Discrete Software ASTs
- **The Problem**: Neuroscience models operate on continuous firing rates and synaptic weights, whereas software engineering operates on discrete Abstract Syntax Trees, file paths, and unit test assertions. Existing agent frameworks treat memory as either purely textual RAG (flat chunks) or static knowledge graphs (unweighted triples).
- **Our Solution**: **Bi-Temporal Hebbian Property Graph**. Every code symbol and file is a graph node. Synaptic edges store a dynamic weight $w_{ij} \in [0, 1]$ that updates via Three-Factor Neuromodulation based on automated test results ($R = \pm 1$). Successful bug fixes strengthen the synaptic pathway between the test, the modified file, and the applied skill.

### Gap 2: 100% Free Zero-Cost Embedded Operation
- **The Problem**: Existing enterprise memory systems (Zep, Mem0, Letta) increasingly require Docker containers, external PostgreSQL instances, cloud subscriptions, or commercial vector databases (Pinecone, Qdrant Cloud), creating heavy setup friction and ongoing monthly costs.
- **Our Solution**: **In-Process SQLite-Vec Single-File Architecture**. By embedding DiskANN vector search (`sqlite-vec`), full-text search (`FTS5`), and graph traversals (recursive CTEs) into a single local SQLite database file, our brain system operates with zero cloud infrastructure, zero network ports, and **$0.00/month operating cost**.

### Gap 3: Agent Catastrophic Quota Exhaustion (The Infinite Loop)
- **The Problem**: When coding agents encounter unexpected compiler errors or missing dependencies, they frequently get trapped in infinite repeating loops (retrying the same failing command with minute syntactic variations) until context windows overflow and free API quotas are completely burned.
- **Our Solution**: **Multi-Tier Reflex Circuit Breaker**. We combine OpenHands' 5-pattern deterministic stuck detector (which halts repeating action/error loops in under 4 iterations) with Drex System-1 fast gating (<15ms pre-execution check) and Reflexion verbal failure buffers, forcing the agent to diagnose the root failure before firing any additional tools.
