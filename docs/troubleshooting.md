# Troubleshooting

## Quick checks

```bash
make test                 # all three languages
curl -s localhost:8080/health    # gateway
python3 -c "import sqlite3; c=sqlite3.connect('/tmp/claude_brain.db'); print(c.execute('SELECT COUNT(*) FROM brain_nodes').fetchone())"
```

## Symptom → fix

| Symptom | Most likely cause | Fix |
| :--- | :--- | :--- |
| `make test` fails on TS | vitest root misconfigured | `cd studio && npm install --save-dev jsdom` |
| `make test` fails on Go | missing `go.mod` in subdir | `cd gateway && go mod tidy` |
| `make test` fails on Python | missing `.venv` | `./scripts/bootstrap.sh` |
| Claude Code hangs | gateway not running | Start gateway; verify `ANTHROPIC_BASE_URL` |
| Hooks no-op | hookshim socket path mismatch | Set `CLAUDE_BRAIN_SOCKET=/tmp/claude_brain.sock` |
| Studio empty graph | daemon not streaming | Check daemon log; verify WebSocket URL |
| 429 floods | all keys in cooldown | Wait 60s; add keys in `gateway/config.toml` |
| Drex timeout errors | API key missing from `.env` | Add `DREX_API_KEY=...` to repo-root `.env` |
| DB locked errors | concurrent writers | Busy timeout is 5s; check watchdog restarts |
| Memory > 150 MB | leak in long session | Restart daemon; report with `tracemalloc` output |

## Reset

```bash
pkill -f brain.server
pkill -f gateway
pkill -f hookshim
rm /tmp/claude_brain.db /tmp/claude_brain.sock
./scripts/bootstrap.sh
```