# Card C2: Repository Scaffolding, Tooling & Build System

## Goal
Establish the unified multi-language workspace skeleton. Configure Python virtual environment/dependencies, Go module setup, TypeScript workspace, root Makefile, dev bootstrap script, and legal NOTICE file.

## Owned Paths
- `Makefile`
- `pyproject.toml` or `requirements.txt`
- `go.mod`
- `package.json`
- `scripts/bootstrap.sh`
- `NOTICE`

## Forbidden Paths
- `contracts/`, `research/`

## Inputs
- `research/risks.md` (quarantine rules for NOTICE)
- `research/shortlist.md` (library selections: `sqlite-vec`, `sigma.js`, etc.)

## Acceptance Tests
1. `make test` runs test runners across Python, Go, and TypeScript.
2. `./scripts/bootstrap.sh` successfully sets up Python venv, downloads Go modules, and installs frontend deps.
3. `NOTICE` lists all ported algorithms with proper Apache-2.0 / MIT attribution and disclaims AGPL/GPL.

## Performance Budget
- Clean bootstrap script runs in < 60s on pre-warmed machine.

## Deliverables
- `Makefile`
- `scripts/bootstrap.sh`
- `NOTICE`
- Root dependency manifests

## Report Format
- At most 15 lines: build targets added, language environments verified, NOTICE generated.
