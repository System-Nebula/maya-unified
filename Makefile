.PHONY: setup test tts-check e2e-install e2e-test homepage-deploy docs-serve docs-build

ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

setup:
	@bash scripts/setup-dev.sh

test:
	uv run pytest

tts-check:
	uv run python scripts/check_tts.py

e2e-install:
	cd tests/e2e && bun install

e2e-test:
	cd tests/e2e && bun x playwright test

homepage-deploy:
	@echo "homepage-deploy: build static assets into apps/maya-gateway (see apps/homepage/)"
	@test -d apps/homepage || (echo "apps/homepage not present" >&2; exit 1)

docs-serve:
	cd docs && npm install && npx tsx ./scripts/regenerate-index.ts && npx tsx ./quartz/bootstrap-cli.mjs build --serve

docs-build:
	cd docs && npm ci && npm run install-plugins && npx tsx ./quartz/bootstrap-cli.mjs build
