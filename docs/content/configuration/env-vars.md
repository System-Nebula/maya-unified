---
title: Environment Variables
tags: [configuration, env]
source: .env.example, packages/voice-runtime/config.py
---

# Environment Variables

Maya Unified configuration is layered:

1. **OS environment** — highest priority if already set when process starts
2. **Root `.env`** — primary file (`maya-unified/.env`, copy from `.env.example`)
3. **Legacy `packages/voice-runtime/.env`** — optional overrides
4. **Dashboard settings JSON** — persisted in `data/`, applied via `services/settings/store.py` (overrides many voice fields at runtime)

`services/env_loader.py` loads dotenv on startup; shell exports are not overwritten by file values.

## Gateway & platform

| Variable | Default | Purpose |
|----------|---------|---------|
| `PORT` | `8090` | Uvicorn listen port |
| `ENV` | `production` | Set `development` for hot reload |
| `DATABASE_URL` | — | PostgreSQL async URL for operators, OAuth, platform |
| `SESSION_SECRET` | — | HMAC key for `maya_op_session` cookie |
| `SESSION_COOKIE_SECURE` | `0` | Set `1` behind HTTPS |
| `OPERATOR_DEFAULT_USERNAME` | `admin` | Seed operator username |
| `OPERATOR_DEFAULT_PASSWORD` | `admin` | Seed operator password |

## LLM (`LLMConfig`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `VA_LLM_BASE_URL` | `http://localhost:1234/v1` | OpenAI-compatible endpoint |
| `VA_LLM_API_KEY` | `lm-studio` | API key |
| `VA_LLM_MODEL` | `local-model` | Model id |
| `VA_LLM_TEMPERATURE` | `0.6` | Sampling |
| `VA_LLM_TOP_P` | `0.9` | Nucleus sampling |
| `VA_LLM_MAX_TOKENS` | `220` | Spoken reply length cap |
| `VA_LLM_HISTORY_TURNS` | `6` | Context window (user+assistant pairs) |
| `VA_LLM_DISABLE_THINKING` | `1` | Disable Qwen3 hidden thinking |
| `VA_LLM_NO_THINK_TOKEN` | `/no_think` | Soft prompt token |
| `VA_LLM_REASONING_EFFORT` | *(empty)* | Use `none` for Gemma/reasoning models |
| `VA_LLM_ORCHESTRATOR` | `1` | Enable tool loop before speak |
| `VA_LLM_SYSTEM_PROMPT` | *(Maya default)* | Base character prompt |

Provider selection (LiteLLM, WebLLM) is primarily stored in **dashboard settings** — see [[Voice Runtime/LLM]].

## STT (`STTConfig`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `VA_WHISPER_MODEL` | `small.en` | faster-whisper model |
| `VA_WHISPER_COMPUTE` | `float16` | `int8` on CPU |
| `VA_STT_DEVICE` | `cuda` | `cpu` fallback |
| `VA_STT_LANGUAGE` | `en` | Force language or auto |
| `VA_STT_SAMPLE_RATE` | `16000` | Input audio rate |

## TTS (`TTSConfig`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `VA_TTS_ENABLED` | `1` | Master TTS switch |
| `VA_TTS_MODE` | `clone` | `clone` or `custom` |
| `VA_TTS_DEVICE` | `cuda` | GPU device |
| `VA_TTS_DTYPE` | `bf16` | Model dtype |
| `VA_TTS_CHUNK_SIZE` | `4` | Streaming sub-chunk steps |
| `VA_TTS_DELIVERY` | `full` | `full` / `hybrid` / `off` |
| `VA_TTS_WARMUP` | `1` | Startup warmup synthesis |
| `VA_TTS_REF_AUDIO` | `voices/ref.wav` | Clone reference path |
| `VA_TTS_XVEC_ONLY` | `1` | Reduce reference bleed artifact |
| `VA_TTS_AUTO_INSTRUCT` | `1` | LLM `VOICE:` delivery cues |
| `VA_OUTPUT_VOLUME` | `1.0` | Playback gain |

Full TTS table: [[Voice Runtime/TTS Pipeline]].

## VAD

| Variable | Default | Purpose |
|----------|---------|---------|
| `VA_VAD_AGGRESSIVENESS` | `2` | WebRTC VAD 0–3 |
| `VA_VAD_FRAME_MS` | `30` | 10/20/30 only |
| `VA_VAD_SILENCE_MS` | `500` | End-of-turn silence |
| `VA_VAD_MIN_SPEECH_MS` | `250` | Minimum utterance |
| `VA_VAD_MAX_TURN_MS` | `30000` | Max utterance length |

## Tools & Discord

| Variable | Default | Purpose |
|----------|---------|---------|
| `VA_WEB_TOOLS_ENABLED` | `1` | Web search tools |
| `VA_DISCORD_ENABLED` | `0` | In-agent Discord tools |
| `VA_DISCORD_TOKEN` | — | Bot token |
| `VA_DISCORD_GUILD_ID` | — | Target guild |
| `VA_DISCORD_AUTO_REPLY` | `1` | Auto-respond in channels |
| `VA_OTEL_ENABLED` | `0` | OpenTelemetry traces |
| `VA_LOG_LEVEL` | `INFO` | Logging verbosity |

## Google OAuth

See [[Operations/Google OAuth]] for `GOOGLE_CLIENT_ID`, redirect URIs, `MAYA_OAUTH_DYNAMIC_REDIRECT`, `MAYA_GOOGLE_TOKEN_DIR`.

## Image / platform extras

| Variable | Purpose |
|----------|---------|
| `COMFYUI_API_URL` | Local ComfyUI for [[Packages/Maya Image]] |
| `MAYA_IMAGE_ROOT` | Generated image output dir |
| `DISCORD_TOKEN` | Standalone [[Platform/Maya Bot]] (not voice tools) |

## Data directory

Unified runtime state:

```env
# Set automatically by lifespan if unset:
VA_DATA_DIR=./data
```

Personalities, skills, memory DBs, operator-scoped dirs live here.

## Quick profiles

**Minimal local voice:**

```env
PORT=8090
VA_LLM_BASE_URL=http://localhost:1234/v1
VA_LLM_MODEL=local-model
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/maya_public
SESSION_SECRET=change-me-in-production
```

**Text-only dev (no GPU TTS):**

```env
VA_TTS_ENABLED=0
VA_LLM_ORCHESTRATOR=0
```

## Related

- [[Reference/Environment Index]] — prefix lookup
- `.env.example` in repo root — commented templates
- [[Services/Settings Store]] — runtime overrides
