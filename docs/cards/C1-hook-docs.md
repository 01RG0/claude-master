# Card C1: Claude Code Hook API Grounding & Live Payloads

## Goal
Directly verify the current Claude Code hooks specification against the live binary and official documentation. Confirm event names, stdin/stdout JSON formats, exit code conventions, and context injection mechanisms. Capture real payloads for mocking.

## Owned Paths
- `contracts/hook-payloads.md`
- `docs/claude-code-facts.md`

## Forbidden Paths
- `brain/`, `gateway/`, `hookshim/`, `studio/`

## Inputs
- Local `claude` binary (`/home/rootuser/.local/bin/claude` v2.1.263)
- Anthropic official documentation / binary decompiled inspection
- `research/errata.md` (Item 2)

## Acceptance Tests
1. Documented exact stdin JSON structure received on `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`.
2. Verified exact exit codes required to allow tool (code 0) vs block tool (code 2).
3. Verified the exact JSON key to inject additional context (`hookSpecificOutput.additionalContext`).
4. Provided at least 4 synthetic/captured JSON test fixtures in `contracts/hook-payloads.md`.

## Performance Budget
- Hook lifecycle analysis; zero runtime overhead.

## Deliverables
- `contracts/hook-payloads.md`
- `docs/claude-code-facts.md`

## Report Format
- At most 15 lines: verified event names, exit codes, context injection schema, test fixtures saved.
