# claude-master architecture (rewrite, 2026-10-13)

## Topology

```
┌─────────────┐     ┌──────────────────┐     ┌────────────────┐
│  Claude Code │────▶│  Go gateway      │────▶│ Free providers │
│  (CLI)       │     │  :8080/v1       │     │ (Groq/Cerebras │
└──────┬───────┘     │  cmd/gateway     │     │  Mistral/Gemini)│
       │            └────────┬─────────┘     └────────────────┘
       │ hooks (PreTool/     │
       │ PostTool)           │ Thompson bandit + key-pool cascade + privacy gate
       ▼                     ▼
┌──────────────┐   ┌──────────────────┐
│  hookshim    │──▶│ brain daemon     │
│  (static Go) │   │ (Python, :7700 + │
└──────────────┘   │  Unix socket*)   │
                   └────────┬─────────┘
                            │ SQLite (WAL) + FTS5 (+ vec0 when available)
                   ┌────────┴─────────┐
                   │ Decision Taker   │──▶ Drex console.nace.ai (optional;
                   │ (DrexClient +    │    degraded rule mode when down)
                   │  DecisionTaker)  │
                   └──────────────────┘
                            │
                       ┌────┴─────┐
                       │  studio  │
                       │ (TS)     │
                       └──────────┘
```

`*` Unix socket on POSIX; on Windows use HTTP `POST /hook` directly
(`asyncio.start_unix_server` unsupported — explicit error, see `brain/paths.py`).

## Component responsibilities

| Component | Language | Path | Job |
|---|---|---|---|
| Brain daemon | Python | `brain/` (`server.py`, `store/`, `learning/`, `guard/`, `judge/`, `reflect/`, `sleep/`, `paths.py`) | Store, learning, guard, sleep, judge; HTTP `:7700` (`/hook /outcome /sleep /health`) + Unix-socket bridge |
| Decision Taker | Python | `brain/judge/client.py` + `decision_taker.py` | Drex transport (dynamic model, retries, breaker, cost caps) + typed decisions for gateway/guard/judge/learning/sleep/watchdog |
| Gateway | Go (stdlib-only) | `gateway/` (`server.go`, `adapter_*.go`, `bandit.go`, `cooldown.go`, `config.go`, `privacy.go`, `router.go`, `cmd/gateway/main.go`) | Anthropic-compatible proxy (`/v1/messages` streaming+tools, `/v1/outcome`, `/health`), key pools, bandit routing. Config JSON is source of truth (`config.json`); `config.toml` is a human mirror |
| Hook shim | Go | `hookshim/` (`shim.go`, `main.go`) | Static binary forwarding hook JSON to daemon; fail-open (>50ms/timeout/malformed → exit 0) |
| Watchdog | Go | `watchdog/` (`watchdog.go`, `main.go`) | Health checks, restarts, sleep scheduling |
| Studio | TypeScript | `studio/` | Sigma.js graph viewer, scrubber, inspector |

## Data flow

1. **PreToolUse hook**: Claude Code → hookshim → daemon `handle_hook`
   (stuck-check → `GatingPolicy`/`DecisionTaker.decide_guard` → lessons/FTS context).
2. **PostToolUse hook**: Claude Code → hookshim → daemon learning (Hebbian update).
3. **`/v1/messages`**: Claude Code → gateway → provider adapter → streaming SSE back.
4. **Decisions**: any component → `DecisionTaker` → Drex (cached, budgeted) or
   deterministic fallback; every call logged to `decisions.jsonl` + `docs/decisions.md`.
5. **Viewer**: daemon → studio (snapshot + event stream).

## Persistence

Single SQLite database (default `tempdir/claude_brain.db`, override
`CLAUDE_BRAIN_DB`) with `brain_nodes`/`brain_edges` (bi-temporal),
`brain_nodes_fts`, `lessons`/`lessons_fts`, `skills`/`skills_fts`,
`model_stats`/`key_state`/`request_log`, `sleep_log`, `decisions`, plus
`brain_node_vectors` (vec0, only when sqlite-vec loads).

## Deployment

```bash
python scripts/bootstrap.py          # venv + deps (cross-platform)
python -m brain.server              # :7700 (defaults from brain/paths.py)
cd gateway && go run ./cmd/gateway --config config.json   # :8080
./hookshim --socket ...             # POSIX; Windows: HTTP /hook
cd studio && npm run dev
```

Set `ANTHROPIC_BASE_URL=http://localhost:8080` and `ANTHROPIC_API_KEY=dummy`
before launching Claude Code. Copy `.env.example` → `.env` for real keys
(never commit; `python scripts/secret_scan.py` enforces).
