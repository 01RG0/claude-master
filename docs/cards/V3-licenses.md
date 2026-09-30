# Card V3: Intellectual Property & License Compliance Audit

## Goal
Audit all source code for license compliance. Verify zero GPL or AGPL contamination from quarantined repos (`fcc`, `pyactr`, `new-api`). Complete `docs/licenses.md` and `NOTICE`.

## Owned Paths
- `docs/licenses.md`
- `NOTICE`

## Acceptance Tests
1. Scan all repository code for AGPL/GPL snippets.
2. All ported algorithms have clean MIT/Apache attribution in `NOTICE`.
