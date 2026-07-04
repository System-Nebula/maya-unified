---
title: NixOS Setup
tags: [getting-started, nixos, linux]
aliases: [Getting Started/NixOS]
---

# NixOS Setup

This guide covers developing and running Maya Unified on **NixOS** (and Nix-flake-compatible Linux environments). Nix provides reproducible CUDA, PortAudio, and FFmpeg dependencies through `nix develop`, avoiding manual system library hunting that often breaks Python audio stacks on Linux.

Windows remains the primary target for voice QA, but NixOS is well-supported for gateway development, platform packages, and CI-like reproducibility.

## Prerequisites

Before starting, ensure:

- Nix with flakes enabled (or `direnv` + `flake.nix` if present in repo)
- NVIDIA drivers with `nvidia-smi` working on the host
- `allowUnfree = true` for CUDA/cuDNN packages in `configuration.nix`

See [[Getting Started/Prerequisites]] for Python version (3.11–3.12) and optional Postgres.

## Quick start

```bash
git clone https://github.com/System-Nebula/maya-unified.git
cd maya-unified

nix develop          # enter dev shell with CUDA, FFmpeg, PortAudio
make setup           # uv sync — torch cu124 + platform deps
cp .env.example .env
./launch.sh          # or: python launch.py
```

Stay inside `nix develop` (or direnv-activated shell) for **every** gateway session — leaving the shell removes libraries from PATH/LD_LIBRARY_PATH and breaks `sounddevice` or CUDA linkage.

## configuration.nix hints

Enable unfree packages for NVIDIA:

```nix
{
  nixpkgs.config.allowUnfree = true;
  hardware.opengl.enable = true;
  services.xserver.videoDrivers = [ "nvidia" ];
}
```

Rebuild after changes: `sudo nixos-rebuild switch`

Exact module names vary by NixOS version — consult current NixOS manual for your release.

## Setup details

### make setup

Root `Makefile` typically invokes:

```bash
uv sync
```

This installs workspace members per `pyproject.toml` with PyTorch from the **cu124** uv index (`[[tool.uv.index]]` in pyproject). CUDA version differs from Windows cu128 — both are intentional per platform scripts.

Optional extras:

```bash
uv sync --extra dev --extra mcp --extra otel
```

### Environment

```bash
cp .env.example .env
```

Edit for LM Studio or remote LLM:

```env
VA_LLM_BASE_URL=http://localhost:1234/v1
VA_LLM_MODEL=local-model
DATABASE_URL=postgresql+asyncpg://maya:maya@localhost:5433/maya
SESSION_SECRET=dev-secret-change-in-prod
```

Postgres on NixOS — options:

- `services.postgresql` module in NixOS config
- Docker: `docker run -p 5433:5432 ...`
- Remote managed Postgres

Run migrations:

```bash
cd packages/maya-db
DATABASE_URL=postgresql+asyncpg://maya:maya@localhost:5433/maya \
  uv run alembic upgrade head
```

### Launch

```bash
./launch.sh
# equivalent: uv run python launch.py
```

Gateway listens on `http://0.0.0.0:8090` by default.

## TTS on NixOS

TTS load may fail on first attempt if CUDA libraries are not visible inside the dev shell.

**Degraded mode:** gateway starts without TTS — text chat and Discord text paths still work.

Diagnostics:

```bash
make tts-check
```

Skip TTS entirely during LLM-only development:

```env
VA_TTS_ENABLED=0
```

**CPU fallback:** change Settings → Dictation/Voice device to `cpu` — slow but useful without GPU passthrough.

## LM Studio on Linux

LM Studio supports Linux builds — same flow as [[Getting Started/Windows]]:

1. Load instruct model
2. Start server on `:1234`
3. Configure dashboard Settings → Reasoning

Alternatives native to Linux: **vLLM**, **Ollama** OpenAI mode, **LiteLLM** proxy to cloud APIs.

## Platform stack (optional)

Full arena/discover/research:

```bash
uv sync --all-packages
```

Confirm gateway log: `mounted platform routes`.

ComfyUI for image features requires separate setup — [[Operations/ComfyUI]] — often via Docker on NixOS host with NVIDIA container toolkit.

## direnv workflow

If the repo provides `.envrc`:

```bash
direnv allow
```

Opening the directory auto-enters `nix develop` — recommended for daily dev.

## Differences from Windows setup

| Aspect | Windows | NixOS |
|--------|---------|-------|
| Setup script | `setup_windows.bat` | `make setup` + `nix develop` |
| PyTorch index | cu128 | cu124 |
| Launch | `launch.bat` | `./launch.sh` |
| FFmpeg | winget | nix shell |
| Primary QA target | Yes | Dev/secondary |

## Verification

```bash
curl http://localhost:8090/health
uv run pytest apps/gateway/tests/test_operator_auth.py -q   # with test DB
make tts-check
```

## Troubleshooting

**`libportaudio.so` not found**

Not in nix develop shell — run `nix develop` before launch.

**CUDA available in nvidia-smi but not torch**

Ensure torch cu124 wheel matches driver; check `python -c "import torch; print(torch.cuda.is_available())"` inside dev shell.

**Postgres connection refused**

Verify port mapping — Docker often exposes 5433→5432; DSN must match host port.

**Platform routes unavailable**

Run `uv sync --all-packages`; inspect import errors in gateway stdout.

**SSE disconnects behind nginx**

Configure proxy buffering off — [[Operations/Deployment]].

## Related documentation

- [[Getting Started/Installation]] — general install flow
- [[Getting Started/Prerequisites]] — hardware checklist
- [[Development/Monorepo Conventions]] — uv workspace layout
- [[Development/Testing]] — pytest on Linux
