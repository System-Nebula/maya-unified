---
title: Windows Setup
tags: [getting-started, windows]
aliases: [Getting Started/Windows]
---

# Windows Setup

Windows 10/11 is the **primary development target** for Maya Unified. This tutorial walks through a complete Windows install from clone to first voice conversation, including common fixes for CUDA, TTS load times, and barge-in behavior.

## Overview

You will:

1. Clone the repo and run `setup_windows.bat`
2. Configure `.env` and FFmpeg
3. Start LM Studio
4. Launch the gateway with `launch.bat`
5. Complete operator setup and tune voice settings

Estimated time: **30–60 minutes** including model downloads (TTS first load can add 10+ minutes).

## Step-by-step

### 1. Clone and enter the repository

Open **PowerShell** or **cmd** (not WSL for GPU voice — use native Windows for CUDA audio stack):

```powershell
git clone https://github.com/System-Nebula/maya-unified.git
cd maya-unified
```

Use a short path without spaces, e.g. `C:\dev\maya-unified`.

### 2. Run setup_windows.bat

```powershell
setup_windows.bat
```

The script:

- Creates `.venv` at repo root
- Installs PyTorch with **CUDA 12.8** wheels from PyTorch index
- Runs `pip install -e .` pulling voice dependencies

When finished, activate the venv for manual commands:

```powershell
.venv\Scripts\activate
```

### 3. Manual install (alternative)

If the batch script fails, run steps explicitly:

```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install "torch>=2.7.0" torchaudio --index-url https://download.pytorch.org/whl/cu128
pip install -e ".[mcp,otel]"
```

Match Python version to 3.11 or 3.12 — verify with `py -3.11 --version`.

### 4. Environment file

```powershell
copy .env.example .env
notepad .env
```

Minimum for voice chat:

```env
PORT=8090
VA_LLM_BASE_URL=http://localhost:1234/v1
VA_LLM_MODEL=local-model
```

For operator login, add Postgres and secret:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/maya_public
SESSION_SECRET=replace-with-long-random-string
```

Then run migrations ([[Getting Started/Installation]]).

### 5. Install FFmpeg

```powershell
winget install Gyan.FFmpeg
```

Restart terminal so `ffmpeg` is on PATH. Required for Discord music and MP3 voice uploads.

### 6. LM Studio

1. Install LM Studio for Windows.
2. Download a **chat/instruct** model (7B–8B class models work well locally).
3. Open **Local Server** tab → Start server on port **1234**.
4. Copy the model identifier — paste into `.env` as `VA_LLM_MODEL` or select in dashboard later.

Test:

```powershell
curl http://localhost:1234/v1/models
```

### 7. Launch Maya

```powershell
launch.bat
```

Or:

```powershell
.venv\Scripts\activate
python launch.py
```

Open **http://localhost:8090**

First boot may download Hugging Face TTS weights — watch console logs.

### 8. First-run dashboard

| Screen | When |
|--------|------|
| `/setup` | No operators in database — create admin |
| `/login` | Operators exist — sign in |
| `/` | Authenticated — conversation view |

Default seeded credentials may apply in dev — **change password** under Settings → Account ([[Operations/Operator Auth]]).

### 9. Configure voice

1. **Settings → Reasoning** — pick LM Studio model, run health check
2. **Settings → Voice** — select reference voice or upload ~10–20s clean speech WAV
3. **Settings → Detection** — use **headphones**; start with `barge_mode: smart`
4. Click **Start** on conversation page or `POST /api/voice/agent/start`

Bundled demo voice: [[Getting Started/Bundled Examples]].

## Windows-specific tips

**Headphones reduce false barge-in.** Speakers feeding mic cause the agent to interrupt itself — see [[Voice Runtime/VAD and Barge-in]].

**CUDA out of memory.** Use smaller whisper model (`tiny.en` / `base.en`) in Settings → Dictation, or smaller TTS clone model. Close LM Studio GPU offload if sharing one GPU.

**TTS fails — degraded mode.** Gateway still serves text chat. Run:

```powershell
make tts-check
```

Set `VA_TTS_ENABLED=0` in `.env` to skip TTS load entirely during LLM-only dev.

**Path with spaces.** Move repo to path without spaces if `sounddevice` or native libs fail mysteriously.

**Windows Defender.** Exclude `.venv` and Hugging Face cache from real-time scan during first model download to avoid timeouts.

**Auto-reload.** Set `ENV=development` in `.env` for uvicorn reload — voice-runtime edits are excluded from reload to avoid reloading TTS weights.

## PostgreSQL on Windows

Options:

- Docker Desktop with Postgres 15 image
- Native Postgres installer
- WSL Postgres (gateway on Windows should use `localhost` port forward)

Example Docker:

```powershell
docker run -d --name maya-pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:15
```

## Verification checklist

- [ ] `http://localhost:8090/health` returns OK
- [ ] Settings → Reasoning health check green
- [ ] `/api/voice/agent/status` shows `llm_ok: true`
- [ ] TTS ready or acceptable degraded mode
- [ ] Voice session starts without `voice_in_use` error

## Next steps

- [[Getting Started/Bundled Examples]] — personalities and skills
- [[Platform/Discord Integration]] — Discord bot token in settings
- [[Operations/Optional Services]] — platform stack with `uv sync`
- [[Operations/ComfyUI]] — image generation on Windows with NVIDIA

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `CUDA not available` | Update NVIDIA driver; reinstall torch cu128 wheel |
| LM Studio connection refused | Start server; check port 1234 |
| 401 on all APIs | Login; check SESSION_SECRET and cookies |
| Mic not detected | Windows Privacy → Microphone → allow desktop apps |
| Slow first TTS response | Normal — model warmup; enable `voice.warmup` in settings |

## Related documentation

- [[Getting Started/Installation]] — cross-platform install overview
- [[Getting Started/Prerequisites]] — hardware requirements
- [[Apps/Launch]] — launch.py behavior
