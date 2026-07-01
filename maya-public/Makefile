# Maya public — convenience targets for the feature/maya_music branch.
#
# Most paths assume you're running from the repo root.
# JS/TS toolchain: bun (use `nix-shell -p bun` if bun isn't on PATH).

HOMEPAGE_DIR := apps/homepage
GATEWAY_STATIC := apps/maya-gateway/src/maya_gateway/static
E2E_DIR := tests/e2e

# Local services. Override on the command line if your setup differs:
#   make gateway-dev GATEWAY_PORT=9000
#   make db-create PGPORT=5432
GATEWAY_PORT ?= 8090
PGHOST ?= localhost
PGPORT ?= 5433
PGUSER ?= postgres
PGDATABASE ?= maya_public

# NixOS-friendly Playwright runner: borrow the patched chromium from
# nixpkgs (playwright-driver.browsers) so we don't try to launch a generic
# Linux binary. Override on other distros if needed.
NIX_PLAYWRIGHT_PKGS ?= bun python313 uv playwright-driver.browsers
PLAYWRIGHT_BROWSERS_PATH ?= $(shell nix-shell -p playwright-driver.browsers --run 'echo $$buildInputs' 2>/dev/null | awk '{print $$1}')

WORKSPACE_ROOT ?= $(HOME)/Workspace

.PHONY: help homepage-deps homepage-dev homepage-build homepage-deploy \
        gateway-dev gateway-test e2e-deps e2e-install e2e-test docker-build clean-homepage \
        feeds-migrate ingest-dev ingest-poll ingest-embed ingest-backfill ingest-analyze ingest-parse-intel \
        seed-profiles repair-youtube-channels check-upload-alerts \
        research-test research-flow \
        db-create db-shell slskd-ingest-fixtures slskd-worker slskd-status slskd-probe \
        slskd-export-queue slskd-batch slskd-history-ingest slskd-worker-once slskd-album-grab

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*##"; printf "Usage:\n  make <target>\n\nTargets:\n"} /^[a-zA-Z_-]+:.*##/ { printf "  %-20s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

homepage-deps: ## Install bun deps for the homepage SPA
	cd $(HOMEPAGE_DIR) && bun install

homepage-dev: ## Run the Vite dev server (http://localhost:5173)
	cd $(HOMEPAGE_DIR) && bun run dev

homepage-build: ## Build the homepage SPA into dist/
	cd $(HOMEPAGE_DIR) && bun run build

homepage-deploy: homepage-build ## Build and copy the SPA into the gateway static dir
	mkdir -p $(GATEWAY_STATIC)
	rm -rf $(GATEWAY_STATIC)/*
	cp -R $(HOMEPAGE_DIR)/dist/. $(GATEWAY_STATIC)/

gateway-dev: ## Run the FastAPI gateway in development mode (defaults to :$(GATEWAY_PORT))
	WORKSPACE_ROOT=$(WORKSPACE_ROOT) PYTHONPATH=$(WORKSPACE_ROOT):$(WORKSPACE_ROOT)/src ENV=development PORT=$(GATEWAY_PORT) uv run maya-gateway

gateway-test: ## Run the gateway pytest suite
	uv run --project apps/maya-gateway --with pytest pytest apps/maya-gateway/tests/ -v

e2e-deps: ## Install bun deps in tests/e2e
	cd $(E2E_DIR) && bun install

e2e-install: e2e-deps ## Install bun deps; chromium comes from nixpkgs at runtime
	@echo "Chromium is provided by nixpkgs (playwright-driver.browsers)."
	@echo "Set PLAYWRIGHT_BROWSERS_PATH=$(PLAYWRIGHT_BROWSERS_PATH) when running outside nix-shell."

e2e-test: ## Run the Playwright e2e suite (uses nixpkgs chromium on NixOS)
	@BROWSERS=$$(nix-shell -p playwright-driver.browsers --run 'echo $$buildInputs' | awk '{print $$1}'); \
	cd $(E2E_DIR) && nix-shell -p $(NIX_PLAYWRIGHT_PKGS) --run \
	  "PLAYWRIGHT_BROWSERS_PATH=$$BROWSERS PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 bun x playwright test"

docker-build: ## Build the gateway image (multi-stage: bun homepage + uv Python)
	docker build -t maya-gateway -f apps/maya-gateway/Dockerfile .

clean-homepage: ## Remove the built SPA from the gateway static dir
	rm -rf $(GATEWAY_STATIC)/*

feeds-migrate: ## Run Alembic migrations for the maya-db package
	uv run --project packages/maya-db alembic -c packages/maya-db/alembic.ini upgrade head

ingest-dev: ## Start a Prefect worker that runs the ingest flows
	uv run --project apps/maya-ingest prefect worker start -p default

ingest-poll: ## One-shot: run the subscription poll flow now
	uv run --project apps/maya-ingest maya-ingest poll

seed-profiles: ## Load example operator follow/preferences (requires gateway on :$(GATEWAY_PORT))
	uv run --with httpx python scripts/seed_operator_profile.py --profile example

repair-youtube-channels: ## Resolve @handle YouTube rows to UC… + feed_url in DB
	uv run --with httpx python scripts/repair_youtube_channels.py

check-upload-alerts: ## Verify followed person + poll + gateway SSE health
	MAYA_GATEWAY_URL=http://localhost:$(GATEWAY_PORT) \
	  uv run --with httpx python scripts/check_upload_alerts.py \
	  $(if $(SKIP_GATEWAY),--skip-gateway,)

ingest-embed: ## One-shot: run the embedding batch flow now
	uv run --project apps/maya-ingest maya-ingest embed

ingest-backfill: ## Back-catalogue index one channel (usage: make ingest-backfill CHANNEL=<uuid>)
	@test -n "$(CHANNEL)" || (echo "usage: make ingest-backfill CHANNEL=<uuid>"; exit 2)
	uv run --project apps/maya-ingest maya-ingest backfill $(CHANNEL)

ingest-analyze: ## Analyze one GitHub release entry (usage: make ingest-analyze VIDEO=<uuid>)
	@test -n "$(VIDEO)" || (echo "usage: make ingest-analyze VIDEO=<uuid>"; exit 2)
	uv run --project apps/maya-ingest maya-ingest analyze-release $(VIDEO)

ingest-parse-intel: ## Parse YouTube description intel (usage: make ingest-parse-intel VIDEO=<uuid>)
	@test -n "$(VIDEO)" || (echo "usage: make ingest-parse-intel VIDEO=<uuid>"; exit 2)
	uv run --project apps/maya-ingest maya-ingest parse-intel $(VIDEO)

        research-test: ## Run maya-research + gateway research unit tests
	uv run --project packages/maya-research --with pytest --with pytest-asyncio pytest packages/maya-research/tests/ -v
	uv run --project apps/maya-gateway --with pytest pytest apps/maya-gateway/tests/test_research_routes.py -v

research-flow: ## Run research Prefect flow for a run id (usage: make research-flow RUN=<uuid>)
	@test -n "$(RUN)" || (echo "usage: make research-flow RUN=<uuid>"; exit 2)
	uv run --project apps/maya-ingest maya-ingest research $(RUN)

db-create: ## Create the maya_public database + required extensions (idempotent)
	@psql -h $(PGHOST) -p $(PGPORT) -U $(PGUSER) -tAc \
	  "SELECT 1 FROM pg_database WHERE datname='$(PGDATABASE)'" | grep -q 1 \
	  || psql -h $(PGHOST) -p $(PGPORT) -U $(PGUSER) \
	     -c "CREATE DATABASE $(PGDATABASE) OWNER $(PGUSER);"
	@psql -h $(PGHOST) -p $(PGPORT) -U $(PGUSER) -d $(PGDATABASE) \
	  -c 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"; CREATE EXTENSION IF NOT EXISTS vector;'

db-shell: ## Open psql against $(PGDATABASE)
	@psql -h $(PGHOST) -p $(PGPORT) -U $(PGUSER) -d $(PGDATABASE)

slskd-ingest-fixtures: ## Ingest breakcore + Dom & Roland + Porter/Nina fixtures into ontology
	cd $(WORKSPACE_ROOT) && uv run scripts/ingest_slskd_batch.py --all-fixtures --reconcile-porter-nina

slskd-worker: ## Run one slskd acquisition batch (ontology open_request tracks)
	cd $(WORKSPACE_ROOT) && uv run --script scripts/slskd_acquisition_worker.py -- --once

slskd-worker-loop: ## Daemon: poll ontology and enqueue slskd downloads
	cd $(WORKSPACE_ROOT) && uv run --script scripts/slskd_acquisition_worker.py -- --loop

slskd-status: ## List slskd transfer status via music query CLI
	uv run scripts/music_query_cli.py status

slskd-probe: ## Search one track via slskd (usage: make slskd-probe ARTIST=TOKYOPILL TITLE=Ethereal)
	@test -n "$(ARTIST)" || (echo "usage: make slskd-probe ARTIST=... TITLE=..."; exit 2)
	uv run scripts/music_query_cli.py search --artist "$(ARTIST)" --title "$(TITLE)" --jsonl

slskd-export-queue: ## Export ontology open_request tracks to Vault markdown queue
	cd $(WORKSPACE_ROOT) && .venv/bin/python scripts/export_slskd_queue.py

slskd-batch: ## Run Vault markdown queue batch against slskd
	cd $(WORKSPACE_ROOT) && .venv/bin/python scripts/process_music_request_batch.py --batch-size 3

slskd-history-ingest: ## Mine 90d Firefox history into ontology and export queue
	cd $(WORKSPACE_ROOT) && .venv/bin/python scripts/music_history_ingest.py --days-back 90 --export-queue

slskd-worker-once: ## Run one ontology acquisition worker batch
	cd $(WORKSPACE_ROOT) && .venv/bin/python scripts/slskd_acquisition_worker.py --once --skip-acapella --max-runtime 120

slskd-album-grab: ## Grab full album from slskd (usage: make slskd-album-grab RELEASE=dom-roland-looking-glass)
	@test -n "$(RELEASE)" || (echo "usage: make slskd-album-grab RELEASE=slug"; exit 2)
	cd $(WORKSPACE_ROOT) && .venv/bin/python scripts/slskd_album_grab.py --release "$(RELEASE)"
