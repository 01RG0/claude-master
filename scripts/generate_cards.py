import os
from pathlib import Path

cards_dir = Path("/home/rootuser/claude-master/docs/cards")
cards_dir.mkdir(parents=True, exist_ok=True)

cards = {
    "C0-contracts.md": """# Card C0: Shared Contracts & Interface Definitions

## Goal
Define and freeze the foundational data contracts across Python, Go, and TypeScript. Refine the SQLite schema, WebSocket event schemas, OpenAPI specifications, and Gateway configuration schemas so all subsequent builder cards can implement against concrete, immutable interfaces.

## Owned Paths
- `contracts/schema.sql`
- `contracts/brain.openapi.yaml`
- `contracts/events.md`
- `contracts/gateway-config.schema.json`

## Forbidden Paths
- All files outside `contracts/`

## Inputs
- `research/architecture-fit.md` (Section 4 SQLite schema)
- `research/track-1-memory.md` (bi-temporal edge definitions)
- `research/track-3-routers.md` (gateway configuration models)
- `research/track-7-graph-viz.md` (synaptic event types)

## Acceptance Tests
1. `contracts/schema.sql` parses cleanly in SQLite with all foreign keys and virtual tables (`vec0`, `fts5`).
2. Schema includes: `brain_nodes`, `brain_edges`, `brain_node_vectors`, `episodic_events`, `model_stats`, `key_state`, `request_log`, `lessons`, `skills`, `sleep_log`, `decisions`.
3. `contracts/brain.openapi.yaml` validates against OpenAPI 3.0 specification.
4. `contracts/gateway-config.schema.json` validates against JSON Schema Draft-07.

## Performance Budget
- Schema definitions must support sub-5ms indexed lookups on a 100,000 edge graph.

## Deliverables
- `contracts/schema.sql`
- `contracts/brain.openapi.yaml`
- `contracts/events.md`
- `contracts/gateway-config.schema.json`

## Report Format
- At most 15 lines: contracts created, validation results, open issues, version tag.
""",

    "C1-hook-docs.md": """# Card C1: Claude Code Hook API Grounding & Live Payloads

## Goal
Directly verify the current Claude Code hooks specification against the live binary and official documentation. Confirm event names, stdin/stdout JSON formats, exit code conventions, and context injection mechanisms. Capture real payloads for mocking.

## Owned Paths
- `contracts/hook-payloads.md`
- `docs/claude-code-facts.md`

## Forbidden Paths
- `brain/`, `gateway/`, `hookshim/`, `studio/`

## Inputs
- Local `claude` binary (`/home/rootuser/.local/bin/claude` v2.1.263)
- Anthropic official documentation / binary decompiled inspection
- `research/errata.md` (Item 2)

## Acceptance Tests
1. Documented exact stdin JSON structure received on `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`.
2. Verified exact exit codes required to allow tool (code 0) vs block tool (code 2).
3. Verified the exact JSON key to inject additional context (`hookSpecificOutput.additionalContext`).
4. Provided at least 4 synthetic/captured JSON test fixtures in `contracts/hook-payloads.md`.

## Performance Budget
- Hook lifecycle analysis; zero runtime overhead.

## Deliverables
- `contracts/hook-payloads.md`
- `docs/claude-code-facts.md`

## Report Format
- At most 15 lines: verified event names, exit codes, context injection schema, test fixtures saved.
""",

    "C2-scaffold.md": """# Card C2: Repository Scaffolding, Tooling & Build System

## Goal
Establish the unified multi-language workspace skeleton. Configure Python virtual environment/dependencies, Go module setup, TypeScript workspace, root Makefile, dev bootstrap script, and legal NOTICE file.

## Owned Paths
- `Makefile`
- `pyproject.toml` or `requirements.txt`
- `go.mod`
- `package.json`
- `scripts/bootstrap.sh`
- `NOTICE`

## Forbidden Paths
- `contracts/`, `research/`

## Inputs
- `research/risks.md` (quarantine rules for NOTICE)
- `research/shortlist.md` (library selections: `sqlite-vec`, `sigma.js`, etc.)

## Acceptance Tests
1. `make test` runs test runners across Python, Go, and TypeScript.
2. `./scripts/bootstrap.sh` successfully sets up Python venv, downloads Go modules, and installs frontend deps.
3. `NOTICE` lists all ported algorithms with proper Apache-2.0 / MIT attribution and disclaims AGPL/GPL.

## Performance Budget
- Clean bootstrap script runs in < 60s on pre-warmed machine.

## Deliverables
- `Makefile`
- `scripts/bootstrap.sh`
- `NOTICE`
- Root dependency manifests

## Report Format
- At most 15 lines: build targets added, language environments verified, NOTICE generated.
""",

    "B1-store.md": """# Card B1: Brain Store & SQLite-Vec Hybrid Engine

## Goal
Build the core storage subsystem in `brain/store`. Implement SQLite database management with dynamic `sqlite-vec` extension loading, full-text FTS5 search, bi-temporal edge tracking (`valid_at`, `invalid_at`), and non-destructive contradiction resolution.

## Owned Paths
- `brain/store/`
- `tests/brain/test_store.py`

## Forbidden Paths
- `gateway/`, `hookshim/`, `studio/`, `contracts/`

## Inputs
- `contracts/schema.sql`
- Shortlist Part 2: `getzep/graphiti` (`edges.py`, `edge_operations.py`)
- Shortlist Part 3: `asg017/sqlite-vec` (`sqlite-vec.c`)

## Acceptance Tests
1. Database initializes with all tables from `contracts/schema.sql`.
2. `sqlite-vec` loads successfully; cosine similarity search on 384-dim embeddings returns expected ranking.
3. Adding a contradicting fact invalidates the previous edge timestamp without deleting historical row.
4. Recursive CTE graph traversal returns connected neighbors up to depth 3 within 2ms.

## Performance Budget
- Vector similarity search (top-5) < 3.0ms on 10k vectors.
- Edge traversal < 2.0ms.

## Deliverables
- `brain/store/db.py`
- `brain/store/graph.py`
- `brain/store/temporal.py`
- `tests/brain/test_store.py`

## Report Format
- At most 15 lines: modules built, test coverage, vector & graph latency results, schema conformance.
""",

    "B2-learning.md": """# Card B2: Neuro-Inspired Learning & Spreading Activation

## Goal
Build `brain/learning`. Implement Three-Factor Neuromodulated Hebbian Learning (LTP on success, LTD on error), FSRS-5 power-law stability decay, and Priority-Queue BFS Spreading Activation for associative context retrieval.

## Owned Paths
- `brain/learning/`
- `tests/brain/test_learning.py`

## Forbidden Paths
- `gateway/`, `hookshim/`, `studio/`, `contracts/`

## Inputs
- `contracts/schema.sql`
- Shortlist Part 4: `open-spaced-repetition/py-fsrs`
- Shortlist Part 5: `HippoRAG` & `nhadaututtheky/neural-memory`
- Shortlist Part 6: `huawjcn/GHL` & `sss777999/Brain`

## Acceptance Tests
1. Hebbian update increases weight on positive reward ($R = 1.0$) and decreases weight on negative reward ($R = -0.8$).
2. FSRS-5 decay function matches power-law retention curve over simulated elapsed intervals.
3. Spreading activation starting from 2 seed nodes traverses causal/reinforcing edges and suppresses refractory loops.
4. Total execution time of spreading activation across 1,000 nodes is < 5ms.

## Performance Budget
- Spreading activation query < 5.0ms.
- Synaptic weight update < 2.0ms.

## Deliverables
- `brain/learning/hebbian.py`
- `brain/learning/fsrs.py`
- `brain/learning/spreading.py`
- `tests/brain/test_learning.py`

## Report Format
- At most 15 lines: algorithms implemented, mathematical verification, benchmark latency, test pass rate.
""",

    "B3-guard.md": """# Card B3: Deterministic Loop Guard & Socket Server

## Goal
Build `brain/guard`. Implement OpenHands 5-pattern stuck detector, working-memory context injection builder, and the non-blocking local Unix domain socket IPC listener.

## Owned Paths
- `brain/guard/`
- `tests/brain/test_guard.py`

## Forbidden Paths
- `gateway/`, `hookshim/`, `studio/`, `contracts/`

## Inputs
- `contracts/schema.sql`
- `contracts/hook-payloads.md`
- Shortlist Part 1: `OpenHands/software-agent-sdk` (`stuck_detector.py`)

## Acceptance Tests
1. Stuck detector catches 4 repeating identical action-observations and trips circuit breaker.
2. Stuck detector catches alternating ping-pong cycles ($A \to B \to A \to B$).
3. Structural normalizer (`_event_eq`) ignores ephemeral UUIDs and timestamps.
4. Socket server processes hook requests and responds with context injection within 4ms.

## Performance Budget
- Hook socket response latency < 4.0ms end-to-end.
- Event normalizer < 0.5ms per check.

## Deliverables
- `brain/guard/stuck_detector.py`
- `brain/guard/context_builder.py`
- `brain/guard/socket_server.py`
- `tests/brain/test_guard.py`

## Report Format
- At most 15 lines: loop patterns tested, socket IPC latency, circuit breaker behavior.
""",

    "B4-reflect.md": """# Card B4: Reflexion, Skill Store & Nightly Sleep Consolidation

## Goal
Build `brain/reflect` and `brain/sleep`. Implement Reflexion test execution harness with episodic verbal failure reflection, Voyager-style docstring skill library, ExpeL cross-trajectory lesson distiller, and the 4-phase nightly sleep consolidation worker.

## Owned Paths
- `brain/reflect/`
- `brain/sleep/`
- `tests/brain/test_reflect.py`

## Forbidden Paths
- `gateway/`, `hookshim/`, `studio/`, `contracts/`

## Inputs
- Shortlist Part 11: `noahshinn/reflexion` (`reflexion.py`)
- Shortlist Part 12: `MineDojo/Voyager` (`skill.py`)
- Shortlist Part 13: `LeapLabTHU/ExpeL` (`expel.py`)
- Track 2 Sleep Consolidation specifications

## Acceptance Tests
1. Reflexion harness captures failed assertions and formats episodic verbal memory snippet.
2. Skill store saves verified code snippets indexed by synthesized docstrings.
3. ExpeL distiller extracts operational guidelines from paired success/failure traces.
4. Nightly sleep job executes: replay, transitive closure, community abstraction, and multiplicative downscaling ($w \leftarrow w \cdot 0.95$).

## Performance Budget
- Sleep consolidation runs in background with zero disruption to active sessions.

## Deliverables
- `brain/reflect/reflexion.py`
- `brain/reflect/skill_store.py`
- `brain/sleep/consolidator.py`
- `tests/brain/test_reflect.py`

## Report Format
- At most 15 lines: components built, sleep cycle stages verified, test results.
""",

    "B5-gateway.md": """# Card B5: Go Free-Tier Anthropic Gateway & Model Router

## Goal
Build `gateway/` in Go. Implement an Anthropic-compatible `/v1/messages` HTTP proxy sitting directly in Claude Code's primary path. Translate streaming SSE events, manage multi-key cooldown cascades, enforce privacy-aware routing (Gemini public-only), and dispatch models using Thompson Sampling bandit.

## Owned Paths
- `gateway/`
- `tests/gateway/`

## Forbidden Paths
- `brain/`, `studio/`, `contracts/`

## Inputs
- `contracts/gateway-config.schema.json`
- Shortlist Part 8: `BerriAI/litellm` (`CooldownCache`)
- Shortlist Part 9: `lmsys/routellm` & `cli-leader` (Thompson sampling bandit)
- `research/errata.md` (Items 1, 4, 5)

## Acceptance Tests
1. Gateway intercepts `/v1/messages` and streams SSE chunks matching Anthropic protocol format.
2. Simulated 429 response on key 1 immediately triggers cooldown and cascades to key 2.
3. Requests containing sensitive file paths/secrets are blocked from Gemini free tier.
4. Thompson sampling bandit dynamically selects highest-scoring healthy model.

## Performance Budget
- Proxy routing overhead < 5.0ms (excluding upstream LLM network generation time).
- Memory footprint < 30 MB RSS.

## Deliverables
- `gateway/server.go`
- `gateway/router.go`
- `gateway/cooldown.go`
- `gateway/bandit.go`
- `gateway/adapter_*.go`
- `tests/gateway/`

## Report Format
- At most 15 lines: streaming compatibility verified, failover cascade tested, privacy routing verified.
""",

    "B6-shim-dog.md": """# Card B6: Fast Go Hook Shim & Watchdog Daemon

## Goal
Build `hookshim/` and `watchdog/` in Go. Compile a sub-5ms static binary `hookshim` called by Claude Code hooks to pass JSON to the brain daemon over Unix sockets with fail-open safety. Build `watchdog` to monitor health and schedule sleep jobs.

## Owned Paths
- `hookshim/`
- `watchdog/`
- `tests/hookshim/`

## Forbidden Paths
- `brain/`, `gateway/`, `studio/`, `contracts/`

## Inputs
- `contracts/hook-payloads.md`
- Shortlist Part 10: Claude Code CLI Native Hooks
- `research/errata.md` (Item 2)

## Acceptance Tests
1. `hookshim` executes in < 3.0ms on cold start.
2. If brain socket is unavailable or times out (>50ms), `hookshim` exits 0 with empty payload (fail-open).
3. If brain socket returns block decision, `hookshim` exits with code 2.
4. `watchdog` detects dead daemon and restarts process within 1s.

## Performance Budget
- Shim total execution time < 3.0ms.

## Deliverables
- `hookshim/main.go`
- `watchdog/main.go`
- `tests/hookshim/`

## Report Format
- At most 15 lines: cold-start latency measurements, fail-open behavior verified, watchdog loop tested.
""",

    "B7-studio.md": """# Card B7: WebGL Synaptic Studio & Scrubber

## Goal
Build `studio/` in TypeScript. Implement the live force-directed synaptic graph viewer using Sigma.js v3, off-thread Graphology ForceAtlas2 worker, custom WebGL traveling pulse shaders, and a 60 FPS HTML5 Canvas replay scrubber with a TypedArray ring buffer.

## Owned Paths
- `studio/`
- `tests/studio/`

## Forbidden Paths
- `brain/`, `gateway/`, `hookshim/`, `contracts/`

## Inputs
- `contracts/events.md`
- Shortlist Part 14: `jacomyal/sigma.js` (WebGL instanced shaders)
- Shortlist Part 15: Custom TypedArray Ring Buffer & Canvas Scrubber

## Acceptance Tests
1. WebGL viewport renders 5,000 nodes and 20,000 edges at steady 60 FPS.
2. GPU traveling wave pulse shader animates synaptic firing along edges without CPU memory reallocations.
3. Canvas time scrubber accurately scrubs through past event ring buffer in `PAUSED` and `REPLAYING` modes.
4. Studio connects to brain WebSocket and updates edge weights in real time.

## Performance Budget
- Rendering: 60 FPS under active physics simulation.
- Replay scrubber seek latency < 16ms (within one frame).

## Deliverables
- `studio/src/graph/`
- `studio/src/shaders/`
- `studio/src/scrubber/`
- `studio/src/ui/`

## Report Format
- At most 15 lines: WebGL FPS benchmarks, pulse shader verification, scrubber state machine tests.
""",

    "B8-judge.md": """# Card B8: Drex Decision Client & Runtime Gating Policy

## Goal
Build `brain/judge`. Integrate the modernized Drex decision client into the brain runtime. Implement pre-execution safety gating, command syntax sanity checks, in-memory decision caching, and fail-open timeout management.

## Owned Paths
- `brain/judge/`
- `tests/brain/test_judge.py`

## Forbidden Paths
- `gateway/`, `hookshim/`, `studio/`, `contracts/`

## Inputs
- `scripts/drex_client.py`
- Shortlist Part 7: Drex System-1 (`POST /v1/systemone`)
- `research/errata.md` (Item 3)

## Acceptance Tests
1. Gating policy classifies dangerous bash commands (e.g. `rm -rf /`, credentials exfiltration) as rejected.
2. Gating policy classifies standard development tools (`git status`, `go test`, `pytest`) as approved.
3. Cache returns identical queries in < 0.2ms without network calls.
4. Any network error or timeout (>150ms) triggers fail-open approval with warning logged.

## Performance Budget
- Cache hit latency < 0.2ms.
- Timeout limit hard-capped at 150ms.

## Deliverables
- `brain/judge/client.py`
- `brain/judge/gating.py`
- `brain/judge/cache.py`
- `tests/brain/test_judge.py`

## Report Format
- At most 15 lines: safety classification accuracy, cache hit latency, fail-open verification.
""",

    "I1-wiring.md": """# Card I1: End-to-End System Wiring & Interconnection

## Goal
Integrate all subsystems into a unified operational pipeline. Connect Claude Code -> Go Gateway -> Free Upstream Providers, Claude Code Hooks -> Hookshim -> Brain Daemon Socket, and Brain Daemon -> WebSocket -> Studio Viewer.

## Owned Paths
- `integration/`
- `scripts/start_brain.sh`
- `scripts/run_session.sh`

## Forbidden Paths
- Core algorithms in `brain/`, `gateway/`, `hookshim/`, `studio/`

## Inputs
- Outputs from all Wave 1 builder cards (B1 to B8)

## Acceptance Tests
1. Single launch script starts Gateway, Brain Daemon, Watchdog, and Studio.
2. Simulated Claude Code session runs commands through hooks and receives working memory context.
3. Real-time synaptic firing pulses appear in Studio viewer over WebSocket during session.
4. Complete session log records Hebbian weight changes in SQLite database.

## Performance Budget
- End-to-end hook overhead < 15ms.

## Deliverables
- `scripts/start_brain.sh`
- `scripts/run_session.sh`
- `integration/test_full_pipeline.py`

## Report Format
- At most 15 lines: pipeline connectivity verified, end-to-end dataflow confirmed, launch script tested.
""",

    "V1-contracts.md": """# Card V1: Multi-Language Contract & Schema Validation

## Goal
Independent verification of contract compliance across Python, Go, and TypeScript. Ensure database schemas, WebSocket event envelopes, and API payloads match `contracts/` exactly.

## Owned Paths
- `tests/verification/test_contracts.py`
- `tests/verification/contracts_test.go`

## Forbidden Paths
- `brain/`, `gateway/`, `hookshim/`, `studio/`, `contracts/`

## Inputs
- `contracts/` specifications

## Acceptance Tests
1. Python store models exactly match `contracts/schema.sql`.
2. Go gateway structures serialize to exact `contracts/gateway-config.schema.json`.
3. WebSocket event payloads match `contracts/events.md`.

## Deliverables
- `tests/verification/test_contracts.py`
- `tests/verification/contracts_test.go`
""",

    "V2-security.md": """# Card V2: Security, Privacy & Secret Leakage Audit

## Goal
Independent security and privacy audit. Verify that secrets never leak to logs, DB, or git, that Gemini free-tier receives zero proprietary code, and that Unix socket permissions are strictly enforced.

## Owned Paths
- `tests/verification/test_security.py`
- `docs/security_audit.md`

## Acceptance Tests
1. Regex scan confirms zero API keys in SQLite DB, logs, git commits, or frontend payloads.
2. Gateway unit test proves code diffs are rejected from Gemini public-only route.
3. Socket permissions enforce 0600 user-only access.
""",

    "V3-licenses.md": """# Card V3: Intellectual Property & License Compliance Audit

## Goal
Audit all source code for license compliance. Verify zero GPL or AGPL contamination from quarantined repos (`fcc`, `pyactr`, `new-api`). Complete `docs/licenses.md` and `NOTICE`.

## Owned Paths
- `docs/licenses.md`
- `NOTICE`

## Acceptance Tests
1. Scan all repository code for AGPL/GPL snippets.
2. All ported algorithms have clean MIT/Apache attribution in `NOTICE`.
""",

    "V4-perf.md": """# Card V4: Real Server Performance & Budget Measurements

## Goal
Measure and record actual performance numbers on the real server for all Section 7 budgets. Populate `docs/benchmarks.md`.

## Owned Paths
- `docs/benchmarks.md`
- `scripts/benchmark_runner.py`

## Acceptance Tests
1. Prompt-time injection latency measured on real SQLite database.
2. Hook shim execution overhead measured via time-tracer.
3. Brain daemon and Go gateway memory measured under load.
""",

    "V5-chaos.md": """# Card V5: Chaos Testing & Graceful Degradation

## Goal
Subject the system to catastrophic failure modes: kill the daemon, exhaust provider keys, return 429 floods, send malformed JSON. Prove graceful degradation.

## Owned Paths
- `tests/verification/test_chaos.py`
- `docs/chaos_report.md`

## Acceptance Tests
1. Killing daemon does not crash or block Claude Code (hookshim fails open).
2. All keys exhausted returns clear error without hanging.
3. SQLite busy locks retry without throwing fatal exceptions.
""",

    "V6-e2e.md": """# Card V6: Final System Acceptance Run

## Goal
Execute the final end-to-end acceptance run satisfying all 11 conditions of Section 11 (Definition of Done).

## Owned Paths
- `docs/ACCEPTANCE_REPORT.md`

## Acceptance Tests
1. Verify all 11 items in Section 11 pass on a clean environment.
""",

    "D1-docs.md": """# Card D1: System Documentation, Runbook & Quickstart

## Goal
Complete user-facing and operational documentation: README quickstart, architecture guide, operational runbook, and troubleshooting guide.

## Owned Paths
- `README.md`
- `docs/RUNBOOK.md`
- `docs/ARCHITECTURE.md`

## Acceptance Tests
1. Clean copy-paste setup command brings system up in under 3 minutes.
2. Runbook details recovery procedures for all alert conditions.
"""
}

for filename, content in cards.items():
    file_path = cards_dir / filename
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content.strip() + "\n")

print(f"Successfully generated {len(cards)} task cards in {cards_dir}")
