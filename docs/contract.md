# Contract — what Claude Code sends and requires (rewrite, 2026-10-13)

Sources: Anthropic streaming docs (platform.claude.com, fetched 2026-10-13),
Claude Code model-config docs (code.claude.com, fetched 2026-10-13), live
probes of configured providers (this host), and gateway E2E runs. Docs can
lag — live traffic via gateway `--log-requests` is the tiebreaker (see §7).

## 1. Transport / auth / env

- `ANTHROPIC_BASE_URL` changes *where* requests go, not which model answers.
  Gateway must serve the model the request names or a mapped substitute.
- Auth: `x-api-key` (Anthropic) — gateway accepts anything, routes to pools.
- Model selection precedence: `--model` > `ANTHROPIC_MODEL` > settings `model`
  > default. Subagents inherit the session model unless their frontmatter pins
  one. Gateway sees only the resolved `model` string per request.
- Known model families/aliases: `opus`, `sonnet`, `haiku`, `fable`,
  `sonnet[1m]`, `opus[1m]`, `opusplan`, full IDs (`claude-opus-5-5`, …).
  Gateway MUST map every `claude-*`/alias name to a configured model
  (config `model_aliases` + role mapping), never 422 on unknown names.

## 2. POST /v1/messages (non-streaming)

Request: `{model, max_tokens, system?, messages[], tools?, tool_choice?,
thinking?, cache_control on blocks?, metadata?}`. Message roles: user/assistant
with content blocks: `text`, `image` (base64/url), `document`/`pdf`,
`tool_use{id,name,input}`, `tool_result{tool_use_id,content,is_error}`,
`thinking`, `server_tool_use`, `web_search_tool_result`.
Response: `{id, type:"message", role:"assistant", model, content[],
stop_reason(end_turn|max_tokens|tool_use|stop_sequence|refusal),
stop_sequence, usage{input_tokens, output_tokens, cache_creation_input_tokens,
cache_read_input_tokens, server_tool_use?}}`.

## 3. Streaming SSE (exact shapes — parity required)

Flow: `message_start` (Message, empty content) → per block
`content_block_start` → `content_block_delta`* → `content_block_stop` →
`message_delta`+ (cumulative usage, stop_reason) → `message_stop`.
Also: `ping`, `error` (`{type:"error",error:{type,message}}`), `fallback`
blocks (start+stop, no deltas). Unknown events must be ignored gracefully.
Deltas: `text_delta{text}`, `input_json_delta{partial_json}` (partial JSON
*strings*, chunked per key/value; accumulate until `content_block_stop`),
`thinking_delta{thinking}` + `signature_delta{signature}` just before stop.
`message_delta.usage` is CUMULATIVE. Tool blocks stream args incrementally
(`eager_input_streaming`); SDKs accumulate via `get_final_message()`.

Gateway gaps fixed in rewrite: `input_json_delta` emission (was text-only),
`signature_delta` passthrough-or-strip, `ping` keepalive, `error` mapping.

## 4. Tools

- `tools[]`: `{name, description, input_schema(JSON Schema)}`;
  `tool_choice`: `{auto,any,none,tool{name}}`. `tool_use{id,name,input}` ids
  (`toolu_*`) must round-trip into `tool_result.tool_use_id`. Parallel calls:
  multiple `tool_use` blocks, order preserved. `is_error` results supported.
- Provider limits (measured): name charset/length, nested-schema depth,
  unsupported keywords (`format`, `pattern`, large `enum`) → gateway sanitizes
  per adapter and logs what it dropped. Models without native tools:
  emulated via constrained prompting + JSON repair + retry (success rate
  published per model; below threshold → `not agentic`, routed to
  summary/small roles only).

## 5. Thinking / reasoning

`thinking: {type: enabled|adaptive, budget_tokens?, display?}` with
`thinking` blocks + `signature` (integrity; must round-trip multi-turn).
Map to provider reasoning params where native (DeepSeek-R1, Qwen-QwQ,
o-series `reasoning_effort`); else emulate (reason-then-answer) and mark
`emulated:true`. Never invent signatures.

## 6. Caching

`cache_control: {type:"ephemeral"}` on system/tool blocks. Pass through where
native (Anthropic, Gemini context caching); elsewhere: byte-stable prefixes
+ gateway exact-match/prefix cache where safe. Honest usage fields only —
measured, never faked. `POST /v1/messages/count_tokens` required.

## 7. Real-traffic capture

`gateway --log-requests <dir>` writes redacted (`[REDACTED]` secrets, bodies
truncated 4k) JSONL per request: headers present, model names seen, block
types, tool names, streaming vs not, errors. First captures (this host,
21 requests): `model: claude-sonnet-5-5` always, `stream: true` always,
`max_tokens` 128000, 26 tools, `system:text` + `text`/`tool_use`/`tool_result`
blocks, all mapped to the configured main model. (Full capture log:
`logs/claude-traffic/*.jsonl`, gitignored.)

## 8. Errors Claude Code understands

Map provider errors to Anthropic types: `rate_limit_error`(429),
`overloaded_error`(529/5xx), `authentication_error`(401),
`invalid_request_error`(422 — do NOT retry),
`not_found_error`(404 model), `timeout`. 429 honors `retry-after(-ms)`.
Failover mid-conversation must preserve tool_use/tool_result pairing.

## 9. Context

Claude Code assumes ~200k-1M context. Smaller models: smart truncation that
keeps tool pairs valid + honest `count_tokens` (estimate labeled when no
tokenizer). Roles: main (strongest agentic), small/fast (haiku-class),
subagent (inherits unless pinned), summarizer/vision by capability tags.
