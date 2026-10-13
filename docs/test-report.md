# Test report (rewrite, universal gateway, 2026-10-13, Windows)

## Full suite (real output)

```
python -m pytest -q --tb=no
162 passed in 59.57s        # zero failures, zero skips (Go on PATH, Drex key present)
```

```
cd gateway && go test ./...      # ok — 11 tests incl. vision downgrade + cache + thinking
cd hookshim && go test ./...     # ok — TCP tests pass, Unix tests skip on Windows
cd watchdog && go test ./...     # ok — restart 73ms (see benchmarks)
cd studio && npm test            # 17 passed (5 files)
```

## Live E2E (real APIs, no mocks on happy path)

- `scripts/e2e_gateway_live.py`: **6/6 PASS** (chat/stream/tool-use/multiturn/
  long-stream/outcome; outputs pasted in benchmarks).
- `scripts/e2e_claude_live.py` (real `claude -p` × 3 through gateway):
  **3/3 rc=0** — haiku write (~7–70s), edit+ls (~11–13s), pwd+echo (~8–13s).
  Hooks fired: `hooks_handled=10, sessions=3, episodic_events=10, nodes=2`.
  Traffic: 21 requests, all `claude-sonnet-5-5` → `open-mistral-7b`,
  stream, 128k max_tokens, 26 tools, tool_use/tool_result round-trips.
- `scripts/e2e_claude_matrix.py` (real `claude -p` × 10, one process):
  **10/10 PASS** — S1 multifile, S2 runtests, S3 refactor, S4 debug, S5 skill,
  S6 subagent, S7 hookallow, S8 hookblock, S9 slash, S10 long stream.
  Brain: `episodic_events=29, nodes=6, sessions=8, hooks_handled=31`.
- `scripts/vision_probe.py` (live gemini-2.5-flash): **PASS 200** — image
  inside a tool_result block reaches the model, which described it
  ("solid, vibrant red square"). Root cause of the earlier 400: Gemini's
  OpenAI endpoint rejects `image_url` parts in `tool` messages
  (`Invalid content part type: image_url`); the adapter spec
  `tool_images: "text"` downgrades them to a text placeholder so the turn
  succeeds. Vision in user messages works natively.
- `scripts/conformance.py`: **ministral-8b-latest 8/8 native PASS** (298–698ms);
  gemini-2.5-flash chat/stream/tools PASS (vision tool-message shape downgraded);
  pollinations 7/8 (vision 400-fail, routed around).
- `provider scan`: 17 providers fingerprinted (openai-chat throughout;
  /models found on 9 with keys, none without). `probe`: ministral row all-true;
  pollinations row documents 402-nonstream/stream-200 split.
- `scripts/load_test.py`: 29/50 ok, 21×529 quota (see benchmarks).
- Admin rotation live: add→stats→remove→ban all ok (hashes only).
- DPAPI keystore: round-trip PASS (blob≠plaintext, decrypts).

## Drex vs rules (scripts/eval_drex.py, 100 labeled events)

```
GUARD drex: acc=0.600 (tp=4 tn=20 fp=0 fn=16) cal_err=0.417 lat p50=0 p95=703
GUARD rule: acc=0.700 (tp=8 tn=20 fp=0 fn=12) lat p50=0.007ms
JUDGE drex: acc=1.000 (30/30)
ROUTE drex: valid=30/30
```

**Drex disabled for guard blocking** (0.60 < 0.70; redaction hides
destructiveness — mechanism documented). Drex stays on for judge (1.0),
route, store, sleep. Guard thresholds: N/A (rule block on risky categories).

## Fault injection (mocks only here)

- Daemon down → shim fail-open exit 0 (3 tests, .exe on Windows).
- Drex down → gate fail-open (all risky classes).
- All keys 429 → PickKey empty, fast fail, cooldown doubling bounded.
- Malformed hooks (500-flood, odd types, non-string commands) → allow, capped.
- Truncated tool args → RepairToolArgsJSON unit-tested.
- Hung provider → 25s attempt timeout → failover (found live via groq hangs).

## Honest gaps

- Cohere v2 path (405), Bedrock/Vertex/Azure auth, native prompt-cache
  passthrough, thinking→reasoning mapping, server web_search, gateway
  response cache: not built — documented in compatibility-matrix with
  measured behavior; requests never silently break (logged notes/errors).
- Pollinations non-stream 402 + mistral free-tier 429s: quota-bound flakiness,
  retried honestly, never hidden.
- Groq/Cerebras 403-1010 from this network; gemini retired model IDs.
- Linux CI: `.github/workflows/ci.yml` runs pytest+go+studio on Ubuntu.
- `gateway/server.go:417` context-leak vet warning: pre-existing, fixed this
  wave (`defer cancel()` on the `NewRequestWithContext` error path).
