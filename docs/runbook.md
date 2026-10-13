# Runbook — operating claude-master (rewrite, 2026-10-13)

## Start sequence (clean machine)

```bash
# 0. Keys (optional until you have them; system runs degraded without Drex)
cp .env.example .env   # fill NACE_API_KEY + provider keys; never commit

# 1. Bootstrap (cross-platform; replaces bootstrap.sh on Windows)
python scripts/bootstrap.py
# Linux/macOS alternative: ./scripts/bootstrap.sh

# 2. Brain daemon (defaults: tempdir/claude_brain.db + .sock; override via env)
python -m brain.server --db /tmp/claude_brain.db --socket /tmp/claude_brain.sock
# Windows: omit flags (tempdir defaults) or set CLAUDE_BRAIN_DB/CLAUDE_BRAIN_SOCKET

# 3. Gateway (JSON is source of truth)
cd gateway && go run ./cmd/gateway --config config.json
# or after build: ./gateway --config gateway/config.json

# 4. Hook shim (POSIX Unix socket)
./hookshim  # reads CLAUDE_BRAIN_SOCKET / BRAIN_SOCKET
# Windows: post hook JSON to http://127.0.0.1:7700/hook instead (no AF_UNIX)

# 5. Watchdog
# env: BRAIN_API_URL (default http://127.0.0.1:7700), BRAIN_DAEMON_CMD,
#      BRAIN_HEALTH_INTERVAL_MS, BRAIN_SLEEP_HOUR/MINUTE, BRAIN_ALERT_WEBHOOK
./watchdog

# 6. Studio viewer
cd studio && npm run dev   # or: npm run build && npm run preview
```

## Point Claude Code at the gateway

```bash
export ANTHROPIC_BASE_URL="http://localhost:8080"
export ANTHROPIC_API_KEY="dummy"   # gateway ignores it; routes to free providers
claude
```

## Verify the stack

```bash
curl -s http://localhost:8080/health
curl -s http://127.0.0.1:7700/health
python scripts/bench_brain.py
python -m pytest -q
python scripts/secret_scan.py
```

POSIX socket check:

```bash
echo '{"hook_event_name":"PreToolUse","tool_name":"Bash","input":{"command":"ls"}}' \
  | nc -U /tmp/claude_brain.sock
```

## Nightly sleep job

Runs via the watchdog at `BRAIN_SLEEP_HOUR` (default disabled, `-1`; set `3`
for 03:00 local). Phases: NREM replay (×1.10) → transitive closure (×0.7) →
REM abstraction (ExpeL) → SHY downscale (×0.95, prune <0.02).
`SELECT * FROM sleep_log`. `DecisionTaker.decide_sleep` advises strategy when
Drex is reachable; otherwise the schedule applies (degraded mode).

## Drex / Decision Taker ops

- Key: `NACE_API_KEY` (alias `DREX_API_KEY`) in env or repo-root `.env`.
- Models: dynamic via `GET /v1/models` (no hardcode); override with explicit
  `model=` when needed. Default when omitted: server-side `drex-v2.0`.
- Budget: `DREX_BUDGET_USD` (default 5.0); `DrexClient.cost_summary()` shows
  `{calls, input_tokens, cost_usd, fail_open}`. At cap → rule fallbacks.
- Logs: JSONL (`tempdir/claude-master-logs/decisions.jsonl`, override
  `CLAUDE_DECISIONS_LOG_DIR`) + a human-readable `decisions.md` mirror in the same log dir (never under `docs/`). Every record has
  `request_id` (report to support@nace.ai with failures).
- Timeouts: background 60s + retries (docs-compliant); hook fast-gate 150ms,
  no retries, cache + fail-open (intentional deviation, see ADR-002).

## Adding a provider

1. Add to `gateway/config.json` under `providers[]` (and mirror in `config.toml`).
2. Set `privacy_policy = "public_data_only"` if the provider may train on prompts.
3. Add API key env var (one account only; see `contracts/gateway-config.schema.json`).
4. Restart the gateway.

## Reset the brain

```bash
rm /tmp/claude_brain.db   # or $CLAUDE_BRAIN_DB / %TEMP%\claude_brain.db
python -m brain.server
```

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Claude Code hangs on startup | gateway not running | Start gateway, check `ANTHROPIC_BASE_URL` |
| Hooks silently skipped | hookshim socket mismatch / Windows AF_UNIX | Set `CLAUDE_BRAIN_SOCKET` (POSIX) or POST `/hook` (Windows) |
| Studio shows no nodes | daemon down or socket path wrong | Check daemon `/health`; verify env |
| 429 from gateway | all keys in cooldown | Wait ~60s or add keys; check `/health` |
| Drex calls fail | key missing / network / budget cap | Fail-open is automatic; check `.env`, `cost_summary()` |
| `sqlite-vec extension not available` | optional dep missing | Safe to ignore (vector search disabled) |
| `WinError 193` running hookshim | ELF binary on Windows | Rebuild on Windows (`cd hookshim && go build`) or use HTTP |
