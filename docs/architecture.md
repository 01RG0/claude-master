# claude-master architecture (rewrite, universal gateway, 2026-10-13)

## Topology (Windows native)

```
┌─────────────┐   ANTHROPIC_BASE_URL    ┌──────────────────────────────┐
│ Claude Code │ ──────────────────────▶ │  Go gateway :8080            │
│  (claude-*) │                         │  /v1/messages (+stream/tools) │
└──────┬──────┘                         │  /v1/messages/count_tokens    │
       │ hooks (Pre/PostToolUse)        │  /v1/chat/completions (OpenAI)│
       ▼                                │  /v1/responses (minimal)      │
┌──────────────┐  TCP 127.0.0.1:7772    │  /v1/models /v1/outcome       │
│ hookshim.exe │ ─────────────────────▶ │  /v1/admin/keys|stats (loop)  │
└──────────────┘                        └──────────────┬───────────────┘
       │                                              │ canonical ↔ adapter
       ▼                                              ▼
┌──────────────────┐                     ┌────────────────────────┐
│ brain daemon :7700│                     │ providers (16+custom)  │
│ hooks/learn/guard │                     │ key pools × mirrors    │
│ Decision Taker    │── Drex (judge/route)│ Thompson/priority/rr/  │
└────────┬─────────┘   (guard: rule-only)│ latency/cost + cooldown│
         │ SQLite WAL                     └────────────────────────┘
    ┌────┴─────┐
    │  studio  │
    └──────────┘
```

No Unix sockets on Windows (TCP loopback dual-stack daemon; POSIX keeps the
socket too). Binaries: `hookshim.exe`, `watchdog.exe`, `gateway.exe`,
`provider.exe`. One bootstrap (`scripts\bootstrap.ps1`), one start
(`scripts\start.ps1`).

## Gateway internals

- **Canonical form**: `AnthropicRequest` (messages/blocks/tools/thinking/
  cache_control/tool_choice/temperature/stops). Every provider is an adapter:
  canonical → provider OpenAI-chat (default) per declarative `AdapterSpec`
  (dialect, paths, auth style, stream format, tool limits, vision).
- **Translation** (`adapter_request.go`): system→system, tool_use→tool_calls
  (role coerced to assistant), tool_result→role:tool, image→image_url parts,
  document/thinking/server-tools→logged notes (never silent), tool_choice
  any→required, temperature/top_p/stops passed, unknown names never 422
  (roles/aliases resolve everything, `ResolveModel`).
- **Streaming** (`stream_translator.go`): stateful per-response translator —
  message_start → text/tool_use blocks → `input_json_delta` per arg fragment
  → stops → message_delta (cumulative usage incl. real `cache_read` when
  reported) → message_stop. Multi-choice handled per-choice; `[DONE]`
  terminates; `RepairToolArgsJSON` salvages truncation. Attempt contexts are
  released on body close (`cancelBody`) — never mid-stream.
- **Reliability**: key pools + 429 cascade + cooldown doubling, mirrors,
  per-attempt 25s timeout (hung provider fails over fast), strategies
  (thompson/priority/round-robin/latency EMA/cost + sticky sessions),
  per-key model allowlists, error envelope mapped to Anthropic types with
  `retry-after` semantics, in-flight guard via budgets.
- **Accounting**: per-model calls/errors/latency-EMA/tokens/cached/cost;
  `/v1/admin/stats`. Request logs redacted+truncated (`--log-requests`).
- **Keys**: env + runtime overlay (add/remove/rotate/set-models/pin/ban,
  loopback-only) persisted DPAPI-encrypted on Windows (`keystore_*.go`).

## Brain

Hook IPC (TCP+Unix) → `handle_hook` (stuck → rule gate → lessons/FTS
context) + episodic persistence per hook (proves learning-from-action) +
Hebbian/model_stats on `/outcome`. Decision Taker: Drex for judge/route/
store/sleep (1s fast / 60s bg, budget caps, JSONL log); **guard is rule-only**
(eval: Drex 0.60 < rules 0.70 — redaction hides destructiveness).

## Detection loop

`provider add|scan|probe|validate` → `gateway/capabilities.json`
(measured>declared>assumed) → conformance rows → `docs/compatibility-matrix.md`
→ routing (roles/bans) → re-scan on schedule/events. User config always wins.
