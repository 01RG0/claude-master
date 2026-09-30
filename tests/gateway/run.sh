#!/usr/bin/env bash
# Gateway acceptance tests live in gateway/*_test.go (same module).
set -euo pipefail
cd "$(dirname "$0")/../../gateway"
exec go test ./... -count=1 "$@"
