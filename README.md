# claude-master — quickstart

Build the "brain system" around Claude Code: a free-model gateway, a
learning daemon, and a live web viewer.

## One-command bootstrap

```bash
./scripts/bootstrap.sh   # creates .venv, installs Python/Go/TS deps
make test                # runs pytest + go test + vitest
```

## Start the stack

```bash
# 1. Brain daemon (Python) — store, learning, guard, sleep, judge
python -m brain.server --db /tmp/claude_brain.db --socket /tmp/claude_brain.sock

# 2. Go gateway — Anthropic-compatible /v1/messages that Claude Code talks to
./gateway --config gateway/config.toml

# 3. Hook shim — tiny static binary Claude Code hooks call
./hookshim --socket /tmp/claude_brain.sock

# 4. Watchdog — health checks, restarts, sleep scheduling
./watchdog --brain-socket /tmp/claude_brain.sock --gateway :8080

# 5. Studio viewer
cd studio && npm run build && npm run preview   # or `npm run dev`
```

## Point Claude Code at the gateway

```bash
export ANTHROPIC_BASE_URL="http://localhost:8080"
export ANTHROPIC_API_KEY="dummy"   # gateway ignores it; routes to free providers
claude
```

## Architecture

| Component    | Language | Job                                            |
| ------------ | -------- | ---------------------------------------------- |
| `brain/`     | Python   | Store, learning rules, retrieval, sleep, judge |
| `gateway/`   | Go       | Anthropic-compatible proxy, key pools, router  |
| `hookshim/`  | Go       | Fast static binary forwarding hooks to daemon  |
| `watchdog/`  | Go       | Health checks, restarts, sleep scheduling      |
| `studio/`    | TypeScript | Sigma.js graph viewer, scrubber, inspector    |

See `docs/architecture.md` and `docs/runbook.md`.

## Budgets (measured)

See `docs/benchmarks.md` for real numbers. Targets: hook path < 10 ms,
post-tool learning < 5 ms, daemon memory < 150 MB, cost $0.00.

## Troubleshooting

See `docs/troubleshooting.md`.