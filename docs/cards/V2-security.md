# Card V2: Security, Privacy & Secret Leakage Audit

## Goal
Independent security and privacy audit. Verify that secrets never leak to logs, DB, or git, that Gemini free-tier receives zero proprietary code, and that Unix socket permissions are strictly enforced.

## Owned Paths
- `tests/verification/test_security.py`
- `docs/security_audit.md`

## Acceptance Tests
1. Regex scan confirms zero API keys in SQLite DB, logs, git commits, or frontend payloads.
2. Gateway unit test proves code diffs are rejected from Gemini public-only route.
3. Socket permissions enforce 0600 user-only access.
