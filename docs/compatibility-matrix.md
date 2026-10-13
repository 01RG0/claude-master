# Compatibility matrix — measured, per model (rewrite, 2026-10-13, Windows)

Legend: **native** = provider does it; **emulated** = gateway synthesizes it;
**fail** = does not work (routed around); **flaky** = works but free-tier quota
interferes (numbers show it). Every cell below comes from a real call output
pasted in `docs/test-report.md` or `gateway/conformance.json`.

## Scorecard (gateway/conformance.py, isolated single-provider)

| Scenario | mistral open-mistral-7b | pollinations openai |
|---|---|---|
| chat | native PASS (764ms) | native PASS (245ms) |
| streaming (SSE + tool deltas) | native PASS (events=23, incl. input_json_delta) | native PASS (162ms, events=23) |
| single tool_use | native PASS (tool_use, 476–5140ms) | native PASS (113ms) |
| parallel tools (2 calls) | native PASS (calls=2, ~500ms) | partial (calls=1 — model emits one call) |
| tool-error recovery (is_error) | native PASS | native PASS |
| multi-turn tool loop | native PASS | native PASS |
| vision (image_url parts) | native PASS (200, ~5s) | **fail** (provider 400 — no vision; routed to mistral/vision role) |
| schema edge (bad name sanitize) | native PASS (200, sanitized) | native PASS |
| non-stream under quota loss | **fail** (402/402-class on pollinations 2026-10-13; streaming still 200) | flaky |
| truncation repair | emulated (RepairToolArgsJSON unit-tested; no live truncation observed) | emulated |

## Provider notes (measured)

- **mistral** (`open-mistral-7b`): full agentic. Free-tier RPM is the binding
  constraint: bursts → 429 → cooldown doubling (60s→120s→240s); conformance
  needed retries + isolation. `mistral-small-latest`: 429 tier-limited.
  `mistral-large-latest`: tier_not_allowed (403). TTFT ~475ms.
- **pollinations** (`openai`): fast (chat 245ms, tools 113ms) but quota-flaky:
  non-stream 402 during burn while streaming stayed 200. No vision (400).
  `public_data_only` — never receives internal content (privacy router).
- **groq / cerebras**: 403 Cloudflare-1010 from this network on every model
  tried (Llama 3.3-70b, 3.1-8b) — unreachable here, kept in config for other
  networks. Gateway fails over correctly (proved by 502→recovery runs).
- **gemini** (`2.0-flash-exp`, `1.5-flash`): 404 retired; `2.0-flash`: 404
  "no longer available". Needs model refresh (scan reports).
- **openrouter** free slugs: 404 retired. **cohere** v2 base path: 405
  (wrong API shape — needs dedicated adapter, documented limit).
- **aihubmix**: `/models` lists 30+ models (aggregator) — untested with keys.

## Claude Code sessions (real, ANTHROPIC_BASE_URL → gateway)

| Task | Model | Result |
|---|---|---|
| write haiku.txt (Write) | open-mistral-7b | rc=0, ~7–70s (first run incl. model warmup) |
| append verse + ls (Edit/Bash) | open-mistral-7b | rc=0, ~11–13s |
| pwd + echo (Bash) | open-mistral-7b | rc=0, ~8–13s |
| hooks fire + memory write | — | hooks_handled=10, sessions=3, episodic_events=10, tool nodes=2 |

Traffic: 21 requests, all `model: claude-sonnet-5-5` → mapped `open-mistral-7b`,
stream:true, max_tokens 128000, 26 tools, tool_use/tool_result round-trips.

## What is emulated vs native

- Emulated today: truncated-arg repair, role-alternation coerce, tool-name
  sanitize, bad-schema keyword strip (logged), count_tokens heuristic
  (labeled estimate), keep-alive-less failover, response-cache: NOT built
  (documented gap — prefixes kept byte-stable instead; no fake savings).
- Not built (honest gaps): provider-native prompt caching passthrough
  (only usage passthrough of `cached_tokens` when reported), thinking-block
  mapping (accepted, not forwarded; signatures stay client-side), server-side
  web_search (rejected with logged note, never silently dropped), Cohere v2
  adapter, Bedrock/Vertex/Azure auth (no keys to test; adapter spec ready).
