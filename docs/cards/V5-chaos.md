# Card V5: Chaos Testing & Graceful Degradation

## Goal
Subject the system to catastrophic failure modes: kill the daemon, exhaust provider keys, return 429 floods, send malformed JSON. Prove graceful degradation.

## Owned Paths
- `tests/verification/test_chaos.py`
- `docs/chaos_report.md`

## Acceptance Tests
1. Killing daemon does not crash or block Claude Code (hookshim fails open).
2. All keys exhausted returns clear error without hanging.
3. SQLite busy locks retry without throwing fatal exceptions.
