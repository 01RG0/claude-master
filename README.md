# claude-master

Build the "brain system" around Claude Code: a free-model gateway, a
learning daemon, and a live web viewer. Target platform: native Windows
(PowerShell); Linux is supported via `scripts/bootstrap.sh` + `make`.

## 60-second quickstart (Windows)

One entry command drives everything: `cm` (PowerShell:
`tools\cm\cm.ps1`, cmd: `tools\cm\cm.cmd`).

```powershell
# 1. One-time install: deps + binaries (about a minute)
cm setup

# 2. Start brain daemon, gateway, watchdog
cm start
```

Point Claude Code at the gateway and run it:

```powershell
$env:ANTHROPIC_BASE_URL = "http://localhost:8080"
$env:ANTHROPIC_API_KEY  = "dummy"   # gateway ignores it; routes to free providers
claude
```

Verify everything:

```powershell
cm status   # one screen: gateway / brain / hook IPC up or down
cm doctor   # dependency + config + key checks, each with the exact fix
```

## What it does

Claude Code runs 100% on free models (Groq, Cerebras, Mistral, Gemini,
OpenRouter, ...), with hooks active and the brain learning from every
action. Every request carries a request id you can trace end-to-end at
the gateway; every automated decision is logged (JSONL) with reason and
evidence.

## Components

| Component    | Language   | Job                                            |
| ------------ | ---------- | ---------------------------------------------- |
| `gateway/`   | Go         | Anthropic-compatible proxy, key pools, router, provider CLI |
| `brain/`     | Python     | Store, learning rules, guard, sleep, Drex judge |
| `hookshim/`  | Go         | Fast static binary forwarding hooks to daemon  |
| `watchdog/`  | Go         | Health checks, restarts, sleep scheduling      |
| `studio/`    | TypeScript | Live graph viewer, scrubber, inspector         |
| `tools/cm/`  | PowerShell | The single entry command (`cm`)                |
| `data/`      | JSON       | Detection corpus (provider / model / price data) |
| `scripts/`   | Python+PS  | Bootstrap, start, detection, benchmarks, E2E   |

See `docs/architecture.md` and `docs/runbook.md`.

## Budgets (measured)

See `docs/benchmarks.md` for real numbers. Targets: hook path < 10 ms,
post-tool learning < 5 ms, daemon memory < 150 MB, cost $0.00.

## Tests

```powershell
python -m pytest -q                    # Python (162 tests)
cd gateway; go test -count=1 ./...     # gateway Go package
cd hookshim; go test -count=1 ./...    # hookshim
cd watchdog; go test -count=1 ./...    # watchdog
cd studio; npm test                    # TypeScript (17 tests)
```

## Troubleshooting

See `docs/troubleshooting.md`. For component-level run instructions and
health endpoints, see `docs/runbook.md`.
