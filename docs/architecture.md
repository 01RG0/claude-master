# claude-master architecture

## Topology

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐
│  Claude Code │────▶│  Go gateway  │────▶│ Free providers │
│  (CLI)       │     │  :8080/v1    │     │ (Groq/Cerebras │
└──────┬───────┘     └──────┬───────┘     │  Mistral/Gemini)│
       │                    │              └────────────────┘
       │ hooks (PreTool/   │
       │ PostTool)          │
       ▼                    ▼
┌──────────────┐   ┌──────────────────┐
│  hookshim    │──▶│ brain daemon     │
│  (static Go) │   │ (Python, socket) │
└──────────────┘   └────────┬─────────┘
                            │ SQLite + vec0
                       ┌────┴─────┐
                       │  studio  │
                       │ (TS)     │
                       └──────────┘
```

## Component Responsibilities

| Component | Language | Path | Job |
| :--- | :--- | :--- | :--- |
| Brain daemon | Python | `brain/` | Store, learning, guard, sleep, judge |
| Gateway | Go | `gateway/` | Anthropic-compatible proxy, key pools, bandit routing |
| Hook shim | Go | `hookshim/` | Static binary forwarding hook JSON to daemon |
| Watchdog | Go | `watchdog/` | Health checks, restarts, sleep scheduling |
| Studio | TypeScript | `studio/` | Sigma.js graph viewer, scrubber, inspector |

## Data Flow

1. **PreToolUse hook**: Claude Code → hookshim → daemon guard → allow/block/context.
2. **PostToolUse hook**: Claude Code → hookshim → daemon learning → Hebbian update.
3. **`/v1/messages`**: Claude Code → gateway → provider adapter → streaming SSE back.
4. **Viewer**: daemon → WebSocket → studio (snapshot + event stream).

## Persistence

Single SQLite database (`brain.db`) with:
- `brain_nodes` / `brain_edges` — bi-temporal graph (valid_at, invalid_at, expired_at).
- `brain_node_vectors` — sqlite-vec virtual table (cosine, 384-dim).
- `brain_nodes_fts` — FTS5 full-text index.
- `brain_lessons` / `brain_skills` — verbal memory and distilled skills.
- `model_stats` / `key_state` / `request_log` — gateway routing telemetry.
- `sleep_log` — nightly consolidation audit trail.

## Deployment

```bash
./scripts/bootstrap.sh   # venv + deps
./gateway --config gateway/config.toml
python -m brain.server --db /tmp/brain.db --socket /tmp/brain.sock
./hookshim --socket /tmp/brain.sock
./watchdog --brain-socket /tmp/brain.sock --gateway :8080
cd studio && npm run dev
```

Set `ANTHROPIC_BASE_URL=http://localhost:8080` and `ANTHROPIC_API_KEY=dummy`
before launching Claude Code.