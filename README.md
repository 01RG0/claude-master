# claude-master

Build the "brain system" around Claude Code: a free-model gateway, a
learning daemon, and a live web viewer.

## How to run the project

### 1. Bootstrap (one time, clean machine)

```bash
./scripts/bootstrap.sh
```

Creates a Python virtualenv, installs dependencies for all three languages,
and builds the Go binaries. Takes about a minute.

### 2. Start the components

Start them in this order:

```bash
# 1. Brain daemon (Python) — memory store, learning, guard, sleep, judge
python -m brain.server --db /tmp/claude_brain.db --socket /tmp/claude_brain.sock

# 2. Gateway (Go) — Anthropic-compatible /v1/messages proxy to free providers
./gateway --config gateway/config.toml

# 3. Hook shim (Go) — tiny static binary Claude Code hooks call
./hookshim --socket /tmp/claude_brain.sock

# 4. Watchdog (Go) — health checks, restarts, nightly sleep scheduling
./watchdog --brain-socket /tmp/claude_brain.sock --gateway :8080

# 5. Studio viewer (TypeScript) — live graph of the brain
cd studio && npm run dev
```

### 3. Point Claude Code at the gateway

In a new terminal, before launching Claude Code:

```bash
export ANTHROPIC_BASE_URL="http://localhost:8080"
export ANTHROPIC_API_KEY="dummy"   # gateway ignores it; routes to free providers
claude
```

Claude Code now runs 100% on free models (Groq, Cerebras, Mistral, Gemini),
with hooks active and the brain learning from every action.

### 4. Verify it is working

```bash
# Gateway health
curl http://localhost:8080/health

# Brain daemon
curl http://127.0.0.1:7700/health

# Studio viewer
open http://localhost:5173
```

### 5. Run the tests

```bash
make test
```

Runs pytest (Python), `go test` (Go), and vitest (TypeScript).

## Architecture

| Component    | Language   | Job                                            |
| ------------ | ---------- | ---------------------------------------------- |
| `brain/`     | Python     | Store, learning rules, retrieval, sleep, judge |
| `gateway/`   | Go         | Anthropic-compatible proxy, key pools, router  |
| `hookshim/`  | Go         | Fast static binary forwarding hooks to daemon  |
| `watchdog/`  | Go         | Health checks, restarts, sleep scheduling      |
| `studio/`    | TypeScript | Sigma.js graph viewer, scrubber, inspector      |

See `docs/architecture.md` and `docs/runbook.md`.

## Budgets (measured)

See `docs/benchmarks.md` for real numbers. Targets: hook path < 10 ms,
post-tool learning < 5 ms, daemon memory < 150 MB, cost $0.00.

## Troubleshooting

See `docs/troubleshooting.md`.