# claude-master — multi-language workspace targets
.PHONY: bootstrap test test-py test-go test-ts help

PYTHON ?= .venv/bin/python
PIP    ?= .venv/bin/pip

help:
	@echo "Targets: bootstrap | test | test-py | test-go | test-ts"

bootstrap:
	./scripts/bootstrap.sh

test: test-py test-go test-ts

test-py:
	@if [ ! -x "$(PYTHON)" ]; then echo "Missing .venv; run: make bootstrap"; exit 1; fi
	$(PYTHON) -m pytest -q

test-go:
	@# goprobe/ dirs are overlay-injected into the gateway package at test time
	@# by the Python harness; they must NOT be compiled standalone.
	@# Scope: gateway, hookshim, watchdog only — never `./...` from root.
	cd gateway && go test ./...
	cd hookshim && go test ./...
	cd watchdog && go test ./...

test-ts:
	@if [ ! -d studio/node_modules ]; then echo "Missing studio/node_modules; run: make bootstrap"; exit 1; fi
	cd studio && npm run typecheck && npm test
