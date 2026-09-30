#!/usr/bin/env bash
# Bootstrap Python venv, Go modules, and studio npm deps.
# Performance budget: < 60s on a pre-warmed machine.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Python virtualenv"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install -e ".[dev]"

echo "==> Go modules"
if [[ -f go.mod ]]; then
  go mod tidy
  go mod download
fi
if [[ -f gateway/go.mod ]]; then
  (cd gateway && go mod tidy && go mod download)
fi

echo "==> TypeScript / studio"
if [[ -f package.json ]]; then
  npm install --no-fund --no-audit
fi
if [[ -f studio/package.json ]]; then
  (cd studio && npm install --no-fund --no-audit)
fi

echo "==> Bootstrap complete"
echo "    Python: $(python --version 2>&1)"
echo "    Go:     $(go version 2>&1)"
if command -v node >/dev/null 2>&1; then
  echo "    Node:   $(node --version 2>&1)"
fi
echo "    Run tests with: make test"
