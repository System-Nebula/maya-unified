---
title: Installation
tags: [getting-started, install]
aliases: [Getting Started/Installation]
---

# Installation

This guide walks through installing **Maya Unified** — the combined voice agent, operator dashboard, and optional platform APIs — on your machine. Maya ships as a Python monorepo with one virtual environment at the repository root; you do not install each package separately unless developing isolated libraries.

By the end of this guide you will have a running gateway on port **8090**, a path to configure the reasoning LLM, and optional PostgreSQL for operator login.

## Before you begin

Review [[Getting Started/Prerequisites]] for hardware and software requirements. At minimum you need **Python 3.11 or 3.12** (3.13+ is not supported), an **NVIDIA GPU** strongly recommended for speech models, and an **OpenAI-compatible LLM** endpoint (LM Studio is the default path).

Choose a platform guide for OS-specific commands:

| Platform | Guide |
|----------|-------|
| Windows 10/11 | [[Getting Started/Windows]] |
| NixOS / Linux (dev) | [[Getting Started/NixOS]] |

## Installation flow

```mermaid
flowchart TD
    A[Clone repository] --> B[Run setup script]
    B --> C[Copy .env.example]
    C --> D[Install FFmpeg]
    D --> E[Start LLM server]
    E --> F[launch.py]
    F --> G{Postgres configured?}
    G -->|Yes| H[/setup or /login]
    G -->|No| I[Voice-only dashboard]
    H --> J[Copy bundled examples]
    I --> J
```

## Step 1 — Clone the repository

```powershell
git clone https://github.com/System-Nebula/maya-unified.git
cd maya-unified
```

Prefer a path **without spaces** on Windows — some native audio dependencies break on spaced paths.

## Step 2 — Run the setup script

**Windows** (recommended primary target):

```powershell
setup_windows.bat
```

This script:

1. Creates `.venv` at the **repo root** (not inside packages)
2. Installs PyTorch with CUDA 12.8 wheels
3. Runs `pip install -e .` with voice dependencies (`faster-whisper`, `faster-qwen3-tts`, etc.)

**Linux / NixOS:**

```bash
nix develop    # optional: enter dev shell
make setup     # uv sync with torch cu124 + deps
```

See [[Getting Started/NixOS]] for flake and `allowUnfree` notes.

## Step 3 — Configure environment

```powershell
copy .env.example .env
```

Edit `.env` for your LLM endpoint at minimum:

```env
VA_LLM_BASE_URL=http://localhost:1234/v1
VA_LLM_MODEL=your-model-id
PORT=8090
```

For operator login, add Postgres:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/maya_public
SESSION_SECRET=change-me-to-a-long-random-string
```

Full variable reference: [[Configuration/Environment Variables]] and [[Reference/Environment Index]].

## Step 4 — Install FFmpeg

Required for Discord music, YouTube playback, and non-WAV voice uploads:

```powershell
winget install Gyan.FFmpeg
```

On Linux/NixOS, FFmpeg is typically provided by `nix develop` or system packages.

## Step 5 — Start the reasoning LLM

**LM Studio** (default):

1. Download an instruct model in LM Studio.
2. Start the local server on port **1234**.
3. Note the model id shown in LM Studio — enter it in **Settings → Reasoning** after launch, or set `VA_LLM_MODEL` in `.env`.

Other OpenAI-compatible servers (vLLM, Ollama with OpenAI shim) work by adjusting `reasoning.base_url` in settings.

## Step 6 — Launch Maya

```powershell
launch.bat
```

Equivalent:

```bash
python launch.py
```

`launch.py` checks voice dependencies and prints setup guidance if imports fail. On success, open:

**http://localhost:8090**

## Step 7 — First login (with PostgreSQL)

If `DATABASE_URL` is configured and migrations applied:

1. Visit `/` — redirect to **/setup** when no operators exist
2. Create the first admin account
3. Sign in at [[Operations/Operator Auth]]

Apply migrations before first login:

```bash
cd packages/maya-db
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/maya_public \
  uv run alembic upgrade head
```

Without Postgres, the voice dashboard may run in single-user mode without persistent login.

## Step 8 — Bundled examples

On first start, Maya copies shipped demo assets — see [[Getting Started/Bundled Examples]] for voices, personalities (**Maya-sama**, **Professor Mari**, **Call Center Scammer**), and starter skills.

## Verify installation

| Check | Expected |
|-------|----------|
| `GET http://localhost:8090/health` | `{"ok": true, "service": "maya-unified"}` |
| Settings → Reasoning → health | LLM probe passes |
| Start voice session | `/api/voice/agent/status` shows `ready: true` (TTS may take minutes first load) |
| `make tts-check` | TTS smoke test passes on GPU |

## Optional next steps

| Goal | Action |
|------|--------|
| Full platform APIs | `uv sync --all-packages` — [[Operations/Optional Services]] |
| Google sign-in | [[Operations/Google OAuth]] |
| Discord voice tools | Settings → Discord — [[Platform/Discord Integration]] |
| Image arena bot | ComfyUI + `uv run maya-bot` — [[Platform/Maya Bot]] |

## Troubleshooting

**Setup script fails on torch**

Verify NVIDIA driver installed. On Windows, `setup_windows.bat` pins cu128 index — driver must support CUDA 12.x.

**Gateway starts but TTS unavailable (degraded mode)**

GPU OOM or missing model download. Run `make tts-check`. Set `VA_TTS_ENABLED=0` for text-only dev.

**Cannot reach LLM**

Start LM Studio server; confirm `http://localhost:1234/v1/models` returns JSON.

**Login redirect loop**

Apply DB migrations; check `DATABASE_URL` connectivity.

**Port 8090 in use**

Set `PORT=8091` in `.env` or stop conflicting process.

## Related documentation

- [[Getting Started/Quickstart]] — minimal happy path
- [[Getting Started/Windows]] — Windows-specific tips
- [[Apps/Launch]] — what `launch.py` does
- [[Development/Monorepo Conventions]] — repository layout
