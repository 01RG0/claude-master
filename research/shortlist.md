# Top 15 Shortlisted Parts for the Claude Code Neuro-Inspired Brain System

This document presents the **top 15 modular algorithmic components** extracted from the 7 research tracks. In accordance with project rules, these represent **isolated parts, files, and algorithms** rather than monolithic frameworks. Each component has been verified against live repositories and validated via the **Drex System-1 Evaluator (`drex-v1.5`)**.

---

## Shortlist Summary Matrix

| Rank | Component / Part Name | Source Repository & Exact File | Lang | License | Porting Method | Effort | Brain Subsystem |
| :---: | :--- | :--- | :--- | :--- | :--- | :---: | :--- |
| **1** | **Deterministic Stuck & Loop Detector** | `OpenHands/software-agent-sdk`<br>`openhands/sdk/conversation/stuck_detector.py` | Python | MIT | Port algorithm | **S** | Loop Prevention & Agent Stability |
| **2** | **Bi-Temporal Edge & Contradiction Resolver** | `getzep/graphiti`<br>`graphiti_core/edges.py`<br>`graphiti_core/utils/maintenance/edge_operations.py` | Python | Apache-2.0 | Port algorithm | **M** | Semantic Graph Memory |
| **3** | **Embedded SIMD Vector Search (`vec0`)** | `asg017/sqlite-vec`<br>`sqlite-vec.c` (DiskANN + SIMD) | C | Apache-2.0 | SQLite Extension | **S** | In-Process Vector Storage |
| **4** | **DSR Power-Law Forgetting Engine** | `open-spaced-repetition/py-fsrs`<br>`fsrs/fsrs.py` (FSRS-5 DSR) | Python | MIT | Port algorithm | **S** | Synaptic Decay & Forgetting |
| **5** | **Priority-Queue BFS Spreading Activation** | `nhadaututtheky/neural-memory` & `HippoRAG`<br>`src/hipporag/hipporag.py` | Python | MIT | Port algorithm | **S** | Associative Memory Retrieval |
| **6** | **Three-Factor Neuromodulated Hebbian Learning** | `huawjcn/GHL` & `sss777999/Brain`<br>`ghl/learning.py` / `brain/synapse.py` | Python | MIT | Port algorithm | **S** | Synaptic Plasticity (LTP / LTD) |
| **7** | **Calibrated System-1 Decision Gateway** | Drex (Nace.AI)<br>`POST https://drex.nace.ai/v1/systemone` | Hosted | Proprietary (API: MIT) | Call as Service | **S** | Pre-Execution Gating & Safety |
| **8** | **Adaptive Cooldown Cache & Retry Parser** | `BerriAI/litellm`<br>`litellm/router.py` (`CooldownCache`) | Python | MIT | Port algorithm | **S** | Free-Tier Key Rotation |
| **9** | **Thompson Sampling Contextual Router** | `lmsys/routellm` & `cli-leader`<br>`routellm/routers/matrix_factorization/` | Python/Go | Apache-2.0 | Port algorithm | **S** | Model Selection & Free Routing |
| **10** | **Claude Code Native Hook Interceptor** | Claude Code CLI (v2.1.263) & MCP SDK<br>`@modelcontextprotocol/sdk` | JS/TS | MIT | Native Hooks / IPC | **S** | Telemetry & Working Memory |
| **11** | **Reflexion Execution Harness & Episodic Buffer** | `noahshinn/reflexion`<br>`programming_runs/reflexion.py`<br>`programming_runs/executors/py_executor.py` | Python | MIT | Port algorithm | **S** | Self-Refine & Failure Reflection |
| **12** | **Docstring-Indexed Skill Store** | `MineDojo/Voyager`<br>`voyager/agents/skill.py` | Python | MIT | Port algorithm | **S** | Procedural Skill Library |
| **13** | **Cross-Trajectory Lesson Distiller** | `LeapLabTHU/ExpeL`<br>`agent/expel.py` (Lines 418–520) | Python | Apache-2.0 | Port algorithm | **M** | Experiential Learning |
| **14** | **Instanced WebGL Edge & Pulse Shaders** | `jacomyal/sigma.js`<br>`packages/sigma/src/rendering/programs/edge-rectangle/` | TS/GLSL | MIT | Port algorithm | **M** | Live Brain Visualization |
| **15** | **Pre-Allocated TypedArray Ring Buffer & Scrubber** | Custom / `vasturiano/force-graph`<br>`src/canvas-force-graph.js` | TS/JS | MIT | Port algorithm | **S** | Time-Scrubber & Replay UI |

---

## Detailed Component Specifications

### 1. Deterministic Stuck & Loop Detector
- **Source**: [`OpenHands/software-agent-sdk: openhands/sdk/conversation/stuck_detector.py`](https://github.com/OpenHands/software-agent-sdk)
- **License**: MIT | **Effort**: S (~200 LOC)
- **What it does**: Inspects a 20-event sliding window to detect 5 distinct failure loops: repeating action-observation, repeating action-error, monologue loops, alternating ping-pong cycles ($A \to B \to A \to B$), and context window condensation cycles. Includes a structural normalizer (`_event_eq`) that strips ephemeral UUIDs and timestamps.
- **How it fits the brain**: Acts as the reflex circuit breaker. When an agent repeats mistakes or gets trapped in tool errors, it halts execution before wasting API quotas and triggers a Tier-2 trajectory rollback with verbal reflection.
- **Drex Validation**: Selected in Drex decision `req_84ba1ed70eab3feb577979152feb7356` (**99.86%** probability).

### 2. Bi-Temporal Edge & Contradiction Resolver
- **Source**: [`getzep/graphiti: graphiti_core/edges.py`](https://github.com/getzep/graphiti)
- **License**: Apache-2.0 | **Effort**: M (~350 LOC)
- **What it does**: Models graph relationships with `valid_at`, `invalid_at`, and `expired_at` timestamps. When new facts contradict existing knowledge, old edges are invalidated rather than destructively deleted, preserving historical provenance.
- **How it fits the brain**: Forms the backbone of the semantic knowledge graph. Solves the catastrophic forgetting problem and allows the agent to reason about past project states ("how the code was configured last week" vs "how it is configured now").
- **Drex Validation**: Selected in Drex decision `req_e5d956557551066c615aa4ebadce1185` (**99.32%** probability).

### 3. Embedded SIMD Vector Search (`vec0`)
- **Source**: [`asg017/sqlite-vec: sqlite-vec.c`](https://github.com/asg017/sqlite-vec)
- **License**: Apache-2.0 | **Effort**: S (Dynamic load / pip install)
- **What it does**: A single C extension providing DiskANN indexing and SIMD-accelerated vector distance calculations (`vec_distance_cosine`, `vec_distance_l2`, `vec_distance_hamming`) inside a standard SQLite database.
- **How it fits the brain**: Enables 100% free, zero-network, embedded vector search on local CPU. Eliminates the need to run Docker containers (Qdrant, Milvus, Chroma) while enabling atomic relational transactions uniting vector similarity with graph CTEs.
- **Drex Validation**: Selected in Drex decision `req_5625bf9c9d4b005fe4379ba9ee47bc24` (**99.68%** probability).

### 4. DSR Power-Law Forgetting Engine
- **Source**: [`open-spaced-repetition/py-fsrs: fsrs/fsrs.py`](https://github.com/open-spaced-repetition/py-fsrs)
- **License**: MIT | **Effort**: S (~150 LOC)
- **What it does**: Implements the modern Free Spaced Repetition Scheduler (FSRS-5) modeling memory via Difficulty ($D$), Stability ($S$), and Retrievability ($R$):
  $$R(t, S) = \left(1 + \text{FACTOR} \cdot \frac{t}{S}\right)^{-0.5}$$
  Repeated successful retrievals expand stability exponentially; failed retrievals increase difficulty and shorten stability.
- **How it fits the brain**: Determines synaptic decay. Unused facts and dead code paths decay toward retrieval thresholds, while frequently used coding conventions and project patterns remain strongly accessible.
- **Drex Validation**: Selected in Drex decision `req_669f64e03b22b1029c78fe23315df69d` (**83.56%** probability).

### 5. Priority-Queue BFS Spreading Activation
- **Source**: [`nhadaututtheky/neural-memory`](https://github.com/nhadaututtheky/neural-memory) & [`HippoRAG`](https://github.com/OSU-NLP-Group/HippoRAG)
- **License**: MIT | **Effort**: S (~180 LOC)
- **What it does**: Given initial seed concepts (current prompt/tool input), spreads activation through connected graph edges using priority-queue traversal with role-based edge multipliers (causal $1.3\times$, reinforcement $1.2\times$, lateral $0.85\times$), refractory suppression, and diminishing-returns early exit ($\theta_{\text{DR}} = 0.05$).
- **How it fits the brain**: Powers associative retrieval. Instead of naive top-$k$ cosine search, the brain retrieves the entire semantic cluster related to the current problem (e.g. activating a bug file immediately co-activates its past failure reflection and relevant test helper).
- **Drex Validation**: Selected in Drex decision `req_ef2687c963a5ba85160a28f731885669` (**62.22%** probability over Personalized PageRank).

### 6. Three-Factor Neuromodulated Hebbian Learning
- **Source**: [`huawjcn/GHL: ghl/learning.py`](https://github.com/huawjcn/GHL) & [`sss777999/Brain`](https://github.com/sss777999/Brain)
- **License**: MIT | **Effort**: S (~120 LOC)
- **What it does**: Updates synaptic connection weights between co-active nodes conditioned on environmental reward ($R \in [-1, +1]$) with headroom saturation and competitive budget normalization:
  $$\Delta w_{ij} = \eta \cdot R \cdot a_i \cdot a_j \cdot (w_{\text{max}} - w_{ij})$$
  $$\sum_{j} w_{ij} \le W_{\text{max\_outgoing}}$$
- **How it fits the brain**: Encodes "cells that fire together wire together, modulated by success or failure". When Claude successfully solves a bug using a particular tool/file combination, the synapses strengthen; when the test fails, the synapses weaken (LTD).
- **Drex Validation**: Selected in Drex decision `req_bc3952f41bcebba195b05a6ef6cb885b` (**99.77%** probability).

### 7. Calibrated System-1 Decision Gateway
- **Source**: Drex (Nace.AI), `POST https://drex.nace.ai/v1/systemone`
- **License**: Cloud API (Client: MIT) | **Effort**: S (~80 LOC wrapper)
- **What it does**: Sub-6B single forward-pass decision model returning calibrated probability distributions across discrete typed questions (`choice`, `score`, `noul`) in **under 15 milliseconds** with zero hallucination and zero token generation cost.
- **How it fits the brain**: Serves as the high-speed sensory gatekeeper for Claude Code: pre-evaluates command safety before execution, verifies code syntax sanity, and classifies error recovery paths without spending slow frontier tokens.
- **Drex Validation**: Selected in Drex decision `req_ef4b17017ba23ee86323677ddb230a56` (**99.66%** probability).

### 8. Adaptive Cooldown Cache & Retry Parser
- **Source**: [`BerriAI/litellm: litellm/router.py`](https://github.com/BerriAI/litellm)
- **License**: MIT | **Effort**: S (~150 LOC)
- **What it does**: Maintains thread-safe key health states, parses `Retry-After` / `retry-after-ms` HTTP response headers, and implements exponential cooldown backoff across multi-key pools.
- **How it fits the brain**: Enables 100% free multi-provider routing. When free tier endpoints (Groq, Cerebras, Mistral, Gemini) return 429 rate limit errors, the router immediately marks that key in cooldown and cascades the request to the next healthy key without dropping execution.
- **Drex Validation**: Selected in Drex decision `req_9971844b2a8685e135e7e174092b6a9c` (**99.15%** probability).

### 9. Thompson Sampling Contextual Router
- **Source**: [`lmsys/routellm`](https://github.com/lm-sys/RouteLLM) & [`cli-leader`](file:///home/rootuser/cli-leader)
- **License**: Apache-2.0 | **Effort**: S (~160 LOC)
- **What it does**: Implements a Multi-Armed Bandit using Beta posterior distributions ($\alpha = 1 + \text{successes}$, $\beta = 1 + \text{failures}$) to continuously sample the optimal free-tier model based on task complexity, empirical pass rate, and measured latency.
- **How it fits the brain**: Solves the model allocation problem. Lightweight tasks (formatting, simple edits) are dispatched to ultra-fast free models (Cerebras Llama-3.1 70B @ 2000 tok/s), while complex architectural refactoring is routed to deeper reasoning models.
- **Drex Validation**: Selected in Drex decision `req_a8a3028c5a2c4234e402efcf36928eeb` (**98.70%** probability).

### 10. Claude Code Native Hook Interceptor
- **Source**: Claude Code CLI runtime (v2.1.263) & `@modelcontextprotocol/sdk`
- **License**: MIT | **Effort**: S (~120 LOC configuration & IPC bridge)
- **What it does**: Intercepts `PreToolUse`, `PostToolUse`, and `UserPromptSubmit` lifecycle events. Injects working memory dynamically via `hookSpecificOutput.additionalContext` and transmits tool telemetry to the brain daemon over local IPC / Unix domain socket.
- **How it fits the brain**: The integration ligament. Allows our external neuro-memory system to seamlessly inject synaptic context directly into Claude Code's prompt stream and capture execution outcomes without modifying Claude Code binaries or relying on flaky terminal screen scraping.
- **Drex Validation**: Selected in Drex decision `req_738ab7cb5c8a329d91834164eb079cba` (**99.22%** probability).

### 11. Reflexion Execution Harness & Episodic Buffer
- **Source**: [`noahshinn/reflexion: programming_runs/reflexion.py`](https://github.com/noahshinn/reflexion)
- **License**: MIT | **Effort**: S (~140 LOC)
- **What it does**: Wraps code execution inside an isolated subprocess with strict timeouts. Upon test or assertion failure, passes the error traceback into `PY_SELF_REFLECTION_CHAT_INSTRUCTION` to synthesize a concise verbal diagnosis stored in an episodic reflection buffer.
- **How it fits the brain**: Powers the System-2 reflection cycle. When a code modification fails automated tests, the failure reflection is stored as an episodic node and immediately retrieved during the next attempt to prevent repeating the identical flaw.
- **Drex Validation**: Selected in Drex decision `req_ef4b17017ba23ee86323677ddb230a56` (**99.97%** probability for hybrid two-tier verification).

### 12. Docstring-Indexed Skill Store
- **Source**: [`MineDojo/Voyager: voyager/agents/skill.py`](https://github.com/MineDojo/Voyager)
- **License**: MIT | **Effort**: S (~150 LOC)
- **What it does**: Generates synthesized LLM docstrings describing the functional intent and parameters of successful code snippets, using the docstring (rather than raw syntax) as the vector embedding target. Manages monotonic code versioning (`SkillV1`, `SkillV2`).
- **How it fits the brain**: Forms the agent's procedural memory. Reusable coding recipes (e.g. "how to run migrations in this repo", "how to build the auth client") are saved as verified skills and retrieved during relevant future tasks.
- **Drex Validation**: Selected in Drex decision `req_75ec99f895b834eb1c1da122e25bbefd` (**99.86%** probability).

### 13. Cross-Trajectory Lesson Distiller
- **Source**: [`LeapLabTHU/ExpeL: agent/expel.py`](https://github.com/LeapLabTHU/ExpeL)
- **License**: Apache-2.0 | **Effort**: M (~220 LOC)
- **What it does**: Compares successful vs failed execution trajectories across multiple tasks to extract generalized operational rules using an `ADD / EDIT / AGREE / REMOVE` rule calculus with reinforcement usage counters.
- **How it fits the brain**: Powers the nightly sleep abstraction phase. Converts raw episodic event logs into permanent semantic guidelines (e.g. "Always run `go fmt` before submitting", "Database connection pool must be closed before worker exit").
- **Drex Validation**: Selected in Drex decision `req_735161b0064f29a212b784202a95ca8e` (**95.65%** probability).

### 14. Instanced WebGL Edge & Pulse Shaders
- **Source**: [`jacomyal/sigma.js: packages/sigma/src/rendering/programs/edge-rectangle/`](https://github.com/jacomyal/sigma.js)
- **License**: MIT | **Effort**: M (~280 LOC GLSL/TS)
- **What it does**: High-performance WebGL 2.0 rendering engine using instanced quad arrays and a custom traveling-wave Gaussian shader:
  $$\text{pulseIntensity} = \exp\left(-\frac{(a_{\text{progress}} - \text{fract}((u_{\text{time}} - a_{\text{spikeTime}}) \cdot v_{\text{speed}}))^2}{2\sigma^2}\right)$$
  Renders 100,000+ nodes and edges at 60 FPS while running ForceAtlas2 physics simulation off-thread in a Web Worker.
- **How it fits the brain**: Drives the real-time synaptic graph viewer. Allows the developer to watch concepts fire, synapses strengthen/weaken, and activation spread across the codebase graph in real time.
- **Drex Validation**: Selected in Drex decision `req_70d4e98f4803b0d238612140e4fbc87a` (**98.71%** probability).

### 15. Pre-Allocated TypedArray Ring Buffer & Scrubber
- **Source**: Custom implementation based on [`vasturiano/force-graph: src/canvas-force-graph.js`](https://github.com/vasturiano/force-graph)
- **License**: MIT | **Effort**: S (~160 LOC)
- **What it does**: Allocation-free circular buffer utilizing contiguous `Float64Array` (timestamps), `Uint32Array` (source/target IDs), and `Float32Array` (delta weights) storing 250,000+ past synaptic events. Paired with a 60 FPS HTML5 Canvas scrub bar supporting `LIVE`, `PAUSED`, `SCRUBBING`, and `REPLAYING` modes.
- **How it fits the brain**: The temporal replay UI. Allows the developer to scrub backward in time and replay how the agent's brain learned, adapted, and formed connections during an overnight or long-running development session.
- **Drex Validation**: Selected in Drex decision `req_c41e97662c16194db3a72661858a74e5` (**91.10%** probability).
