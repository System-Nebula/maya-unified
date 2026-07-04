---
title: Repository Map
tags: [architecture]
source: maya-unified/
---

# Repository Map

This page is a **guided map** of the monorepo—what each top-level directory owns, and where to look when debugging a specific symptom.

## Top-level layout

```
maya-unified/
├── launch.py                 # ← START HERE (entrypoint)
├── launch.bat / launch.sh    # Platform wrappers
├── setup_windows.bat         # Windows venv + CUDA torch + pip install -e .
├── pyproject.toml            # Single dependency manifest (uv/pip)
├── .env.example              # Copy to .env
├── data/                     # Runtime state (gitignored) — personalities, memory, skills
├── examples/                 # Bundled assets copied on first launch
├── apps/                     # Deployable applications (gateway, dashboard, platform)
├── packages/                 # Importable libraries (voice-runtime, maya-db, …)
├── services/                 # Shared Python services (hub, auth, settings)
├── scripts/                  # Setup, OAuth verify, TTS check
├── tests/                    # pytest + Playwright e2e
├── infra/                    # ComfyUI docker stack
└── docs/                     # This Quartz documentation site
```

## `apps/` — runnable applications

| Directory | Role | Entry |
|-----------|------|-------|
| **`gateway/`** | Unified FastAPI server | Imported by `launch.py` → `main.run()` |
| **`dashboard/`** | Static HTML/JS/CSS for operators | Served by gateway at `/`, `/settings`, … |
| **`maya-gateway/`** | Platform API package (`maya_gateway` module) | Routers mounted in `gateway/main.py` |
| **`maya-bot/`** | Standalone Discord `/imagine` bot | `uv run maya-bot` |
| **`maya-ingest/`** | Prefect feed ingest worker | Optional batch jobs |

**Rule of thumb:** HTTP-facing code → `apps/gateway/`; platform domain routes → `apps/maya-gateway/`; UI assets → `apps/dashboard/`.

## `packages/` — libraries

| Package | Purpose |
|---------|---------|
| **`voice-runtime/`** | STT, LLM, TTS, agent, memory, tools — [[Voice Runtime]] |
| **`maya-contracts/`** | Shared Pydantic types / API schemas |
| **`maya-db/`** | SQLAlchemy models + Alembic migrations |
| **`maya-research/`** | LangGraph research flows |
| **`maya-image/`** | Image generation clients |
| **`maya-feeds/`** | Feed adapters |
| **`maya-graph/`** | Graph query helpers |

Installed editable from root: `pip install -e .` or `uv sync`.

## `services/` — cross-cutting backend

| Path | Purpose |
|------|---------|
| **`voice/hub.py`** | VoiceHub — unified bridge to VoiceAgent |
| **`voice/inference.py`** | GPU inference lock |
| **`llm/provider.py`** | LLM client factory + hot-swap |
| **`settings/store.py`** | Dashboard settings persistence |
| **`auth/`** | Operator sessions, password hashing |
| **`integrations/google/`** | OAuth, Gmail, Calendar |
| **`paths.py`** | Repo root, DATA_DIR, sys.path setup |
| **`env_loader.py`** | `.env` loading order |

Services are imported by **both** gateway and voice-runtime (after `setup_paths()`).

## `data/` — runtime state (never commit)

| Content | Typical path |
|---------|--------------|
| Personalities | `data/personalities.json` |
| Skills | `data/skills/*.md` |
| Memory DBs | `data/memory/`, cognitive index |
| Operator-scoped dirs | `data/operators/{id}/` |
| Google tokens | `.data/google-tokens/` (also gitignored) |
| Migration marker | `data/.migrated-from-qwen3` |

Voice reference clips default to **`packages/voice-runtime/voices/`** (may be overridden in Settings).

## Where to debug by symptom

| Symptom | First files to open |
|---------|---------------------|
| Won't start / port bind | `launch.py`, `apps/gateway/main.py` |
| 401 on voice API | `apps/gateway/main.py` middleware, `services/auth/` |
| Empty LLM reply | `packages/voice-runtime/llm.py`, LM Studio logs |
| No TTS audio | `packages/voice-runtime/tts.py`, stderr `[tts] WARNING` |
| Settings not applying | `services/settings/store.py`, `services/voice/hub.py` |
| OAuth mismatch | `services/integrations/google/config.py`, `scripts/verify_google_oauth.py` |
| Platform 503 | `packages/maya-db` migrations, `DATABASE_URL` |

## Related

- [[Architecture/Overview]]
- [[Architecture/Architectural Layers]]
- [[Development/Monorepo Conventions]]
