# Card B5: Go Free-Tier Anthropic Gateway & Model Router

## Goal
Build `gateway/` in Go. Implement an Anthropic-compatible `/v1/messages` HTTP proxy sitting directly in Claude Code's primary path. Translate streaming SSE events, manage multi-key cooldown cascades, enforce privacy-aware routing (Gemini public-only), and dispatch models using Thompson Sampling bandit.

## Owned Paths
- `gateway/`
- `tests/gateway/`

## Forbidden Paths
- `brain/`, `studio/`, `contracts/`

## Inputs
- `contracts/gateway-config.schema.json`
- Shortlist Part 8: `BerriAI/litellm` (`CooldownCache`)
- Shortlist Part 9: `lmsys/routellm` & `cli-leader` (Thompson sampling bandit)
- `research/errata.md` (Items 1, 4, 5)

## Acceptance Tests
1. Gateway intercepts `/v1/messages` and streams SSE chunks matching Anthropic protocol format.
2. Simulated 429 response on key 1 immediately triggers cooldown and cascades to key 2.
3. Requests containing sensitive file paths/secrets are blocked from Gemini free tier.
4. Thompson sampling bandit dynamically selects highest-scoring healthy model.

## Performance Budget
- Proxy routing overhead < 5.0ms (excluding upstream LLM network generation time).
- Memory footprint < 30 MB RSS.

## Deliverables
- `gateway/server.go`
- `gateway/router.go`
- `gateway/cooldown.go`
- `gateway/bandit.go`
- `gateway/adapter_*.go`
- `tests/gateway/`

## Report Format
- At most 15 lines: streaming compatibility verified, failover cascade tested, privacy routing verified.
