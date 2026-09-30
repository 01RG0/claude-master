# System Blockers & Escalation Log

*Condition logs for any requirement meeting Section 10 escalation criteria:*
1. Paid service or credit card needed.
2. License violation (GPL/AGPL/unknown) affecting a shortlisted part.
3. Provider terms forbid planned action.
4. Action touches files outside repo or is destructive.
5. Missing real API keys not present in `.env`.
6. High-impact decision unresolved after empirical evidence gathering.

---

## Active Blockers

*No active blockers. All systems green.*

---

## Resolved Blockers

| Date | Issue | Resolution |
| :--- | :--- | :--- |
| 2026-09-30 | Initial Drex client hardcoded paths | Modernized in `scripts/drex_client.py` with dynamic `.env` resolution. |
| 2026-09-30 | `fcc` AGPL & `pyactr` GPL copyleft risk | Quarantined in `research/errata.md`; clean-room porting only. |
| 2026-09-30 | Gemini free-tier data logging | Policy flagged in `research/errata.md` as public-data only. |
