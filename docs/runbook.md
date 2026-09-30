# Runbook — operating claude-master

## Start sequence (clean machine)

```bash
# 1. Bootstrap
./scripts/bootstrap.sh

# 2. Brain daemon
python -m brain.server --db /tmp/claude_brain.db --socket /tmp/claude_brain.sock

# 3. Gateway
./gateway --config gateway/config.toml

# 4. Hook shim
./hookshim --socket /tmp/claude_brain.sock

# 5. Watchdog
./watchdog --brain-socket /tmp/claude_brain.sock --gateway :8080

# 6. Studio viewer
cd studio && npm run build && npm run preview
```

## Point Claude Code at the gateway

```bash
export ANTHROPIC_BASE_URL="http://localhost:8080"
export ANTHROPIC_API_KEY="dummy"   # gateway ignores it; routes to free providers
claude
```

## Verify the stack

```bash
# Gateway health
curl -s http://localhost:8080/health

# Brain daemon socket
echo '{"hook_event_name":"PreToolUse","tool_name":"Bash","input":{"command":"ls"}}' \
  | nc -U /tmp/claude_brain.sock

# Studio
open http://localhost:5173
```

## Nightly sleep job

Runs automatically via the watchdog at 03:00 local. Phases:
1. NREM replay — strengthen replayed trajectories (×1.10).
2. Transitive closure — A→B ∧ B→C ⇒ A→C.
3. REM abstraction — community concept nodes + ExpeL distillation.
4. SHY downscale — w ← w · 0.95, prune below 0.02.

Log visible in the studio "Sleep" tab and queryable via `SELECT * FROM sleep_log`.

## Adding a provider

1. Add to `gateway/config.toml` under `[providers.<name>]`.
2. Set `data_policy = "public-data-only"` if the provider may train on prompts.
3. Add API keys (one per account, per Section 5 of the master spec).
4. Reload the gateway: `kill -HUP $(pgrep gateway)`.

## Reset the brain

```bash
rm /tmp/claude_brain.db
python -m brain.server --db /tmp/claude_brain.db --socket /tmp/claude_brain.sock
```

## Common failures

| Symptom | Cause | Fix |
| :--- | :--- | :--- |
| Claude Code hangs on startup | gateway not running | Start gateway, check `ANTHROPIC_BASE_URL` |
| Hooks silently skipped | hookshim binary missing | Rebuild: `cd hookshim && go build -o ../hookshim .` |
| Studio shows no nodes | daemon down or socket path wrong | Check `CLAUDE_BRAIN_SOCKET` env var |
| 429 from gateway | all keys for provider in cooldown | Wait ~60s or add more keys; check `/health` |
| Drex calls fail | API key missing or network | Fail-open is automatic; check `.env` |