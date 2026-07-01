.PHONY: help up down logs fetch-zimage fetch-krea2

COMFY_HOME ?= $(HOME)/ComfyUI
COMFY_DIR := ComfyUI
REPO_ROOT := $(abspath ../..)

help:
	@echo "ComfyUI local dev stack (Salad comfyui-api + your ComfyUI data dir)"
	@echo ""
	@echo "  make fetch-zimage   Download Z-Image Turbo weights (requires HF_TOKEN)"
	@echo "  make fetch-krea2    Download Krea 2 Turbo weights (requires HF_TOKEN)"
	@echo ""
	@echo "Build/run: clone SaladTechnologies/comfyui-api into $(COMFY_DIR),"
	@echo "copy docker-compose.yml, set COMFY_HOME=$(COMFY_HOME), then docker compose up -d"

fetch-zimage:
	uv run python scripts/fetch_zimage_weights.py --comfy-home "$(COMFY_HOME)" $(ARGS)

fetch-krea2:
	uv run python scripts/fetch_krea2_weights.py --comfy-home "$(COMFY_HOME)" $(ARGS)

up:
	@test -d "$(COMFY_DIR)" || (echo "Missing $(COMFY_DIR)/ — see README.md"; exit 1)
	cd $(COMFY_DIR) && COMFY_HOME="$(COMFY_HOME)" docker compose up -d

down:
	cd $(COMFY_DIR) && docker compose down

logs:
	cd $(COMFY_DIR) && docker compose logs -f comfyui-api
