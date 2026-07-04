---
title: Prerequisites
tags: [getting-started]
aliases: [Getting Started/Prerequisites]
---

# Prerequisites

Maya Unified combines **local speech models**, an **OpenAI-compatible LLM**, and optionally **PostgreSQL** and **ComfyUI** for platform features. This page lists what you need before following [[Getting Started/Installation]] — use it as a checklist when provisioning a dev machine or GPU server.

## Requirements summary

| Requirement | Required? | Notes |
|-------------|-----------|-------|
| Python 3.11–3.12 | **Yes** | 3.13+ not supported — check `requires-python` in root `pyproject.toml` |
| NVIDIA GPU | Strongly recommended | STT + TTS on CPU is slow; CUDA expected in defaults |
| FFmpeg | **Yes** for full features | Voice upload formats, Discord/YouTube audio |
| LM Studio or LLM API | **Yes** for chat | Default `http://localhost:1234/v1` |
| PostgreSQL 15+ | For auth/OAuth/platform | Optional for voice-only experiments |
| Node.js ≥ 22 | Docs site only | Building Quartz docs in `docs/` — not runtime |
| ComfyUI + GPU | Image/arena only | See [[Operations/ComfyUI]] |
| Discord bot token | Discord features only | Two surfaces — [[Platform/Discord Integration]] |

## Hardware guidance

### GPU (voice)

Default settings assume **CUDA** for:

- **STT:** faster-whisper (`dictation.device: cuda`)
- **TTS:** Qwen3 TTS models (`voice.device: cuda`)

VRAM needs vary by model sizes — plan for **8 GB minimum**, **12–16 GB comfortable** for default clone + small.en whisper together.

CPU-only fallback is possible by changing settings after install, but latency increases sharply.

### GPU (image — optional)

ComfyUI arena workflows may need **additional VRAM** beyond voice. Running voice gateway and ComfyUI on one GPU requires careful memory management or sequential use.

### Disk

- Python venv + torch: **several GB**
- TTS/STT model caches: **multiple GB** (Hugging Face downloads)
- ComfyUI checkpoints: **tens of GB** if enabling image features

## Software stack

### Python environment

Single root `.venv` — see [[Development/Monorepo Conventions]]. Do not use Python 3.13 until project metadata updates.

**Windows:** `setup_windows.bat` installs PyTorch cu128 wheels.

**NixOS:** `make setup` via uv with cu124 index — stay inside `nix develop` for PortAudio, FFmpeg, CUDA runtime libs.

### FFmpeg

Used by:

- Voice reference upload validation (MP3/M4A via ffprobe)
- Discord music tool (`yt-dlp` pipe)
- Audio format conversion in playback path

Install:

```powershell
winget install Gyan.FFmpeg
```

Verify: `ffmpeg -version`

### LM Studio (default LLM)

1. Download from [lmstudio.ai](https://lmstudio.ai)
2. Load an **instruct** chat model (not embedding-only)
3. Start **Local Server** on port 1234
4. Enable CORS if browser WebLLM paths need it

Alternatives: vLLM, Ollama (OpenAI compatibility mode), cloud APIs via LiteLLM settings.

### PostgreSQL (optional tier)

Required for:

- Operator accounts ([[Operations/Operator Auth]])
- Google OAuth state and connections ([[Operations/Google OAuth]])
- Voice rooms, platform arena/discover/research

Quick Docker example:

```bash
docker run -d --name maya-pg -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 postgres:15
```

Enable pgvector for platform embeddings:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### Node.js (documentation only)

Only if building the docs site:

```bash
cd docs && npm install && npm run build
```

Runtime gateway does not require Node.

## Voice pipeline dependencies

Installed automatically by setup scripts:

| Package | Role |
|---------|------|
| `faster-whisper` | Speech-to-text |
| `faster-qwen3-tts` | Streaming text-to-speech |
| `torch` / `torchaudio` | GPU inference |
| `sounddevice` | Local mic capture |
| `webrtcvad-wheels` | Voice activity detection |

`launch.py` checks imports and prints remediation if voice deps missing.

Optional extras:

```bash
pip install -e ".[mcp,otel]"
# or: uv sync --extra dev --extra mcp --extra otel
```

## Network and ports

| Port | Service |
|------|---------|
| 8090 | Unified gateway (default) |
| 1234 | LM Studio OpenAI API |
| 5432 | PostgreSQL |
| 3000 | comfyui-api (optional) |
| 8001 | VTube Studio (optional) |

Ensure firewall rules allow localhost loopback for dev; production needs TLS termination — [[Operations/Deployment]].

## Pre-flight checklist

- [ ] Python 3.11 or 3.12 in PATH
- [ ] NVIDIA driver + `nvidia-smi` works
- [ ] 20+ GB free disk for models
- [ ] FFmpeg installed
- [ ] LM Studio model loaded and server running
- [ ] Postgres running with migrations (if using auth)
- [ ] Headphones available for voice testing (reduces false barge-in)

## Related documentation

- [[Getting Started/Installation]] — step-by-step install
- [[Getting Started/Windows]] — Windows-specific setup
- [[Getting Started/NixOS]] — NixOS dev shell
- [[Voice Runtime]] — voice engine overview
