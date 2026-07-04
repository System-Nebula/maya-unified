import fs from "fs"
import path from "path"

const ROOT = path.join(import.meta.dirname, "..", "content")

function write(rel, body) {
  const file = path.join(ROOT, rel)
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, body.trimStart() + "\n")
}

write("index.md", `---
title: Maya Unified
description: Local voice AI with web dashboard, Discord tools, memory, and optional platform APIs.
tags: [getting-started, overview]
aliases: [home]
---

# Maya Unified

Local voice AI with a web dashboard: mic → Whisper → LLM → Qwen3-TTS, plus Discord tools, memory, and optional platform APIs (arena, discover, research).

**One repo. One clone. One venv. One launcher.**

\`\`\`bash
git clone https://github.com/System-Nebula/maya-unified.git
cd maya-unified
setup_windows.bat    # or see [[Getting Started/NixOS]]
launch.bat           # → http://localhost:8090
\`\`\`

## What's inside

Voice and platform code live **in this repository** — not as external subprojects:

| Area | Path | Role |
|------|------|------|
| Voice engine | \`packages/voice-runtime/\` | STT, TTS, agent, Discord, memory, tools |
| Unified gateway | \`apps/gateway/\` | FastAPI entry mounted by [[Apps/Launch]] |
| Dashboard | \`apps/dashboard/\` | Operator web UI |
| Platform | \`apps/maya-gateway/\`, \`packages/maya-*\` | Arena, research, image, feeds |
| Services | \`services/\` | Voice hub, auth, settings, integrations |

Runtime state is always under \`data/\` at the repo root.

## Documentation map

\`\`\`mermaid
flowchart TB
  GS[[Getting Started]] --> ARCH[[Architecture]]
  ARCH --> VR[[Voice Runtime]]
  ARCH --> APPS[[Applications]]
  APPS --> PLAT[[Platform]]
  PLAT --> PKG[[Packages]]
  APPS --> SVC[[Services]]
  GS --> CFG[[Configuration]]
  CFG --> OPS[[Operations]]
  OPS --> DEV[[Development]]
  DEV --> REF[[Reference]]
\`\`\`

## Quick links

- [[Getting Started/Installation]] — Windows, NixOS, prerequisites
- [[Getting Started/Quick Start]] — first session in five minutes
- [[Architecture/Overview]] — system design and layers
- [[Architecture/Launch Flow]] — \`launch.py\` → gateway startup
- [[Voice Runtime/Agent Orchestrator]] — turn loop and tools
- [[Configuration/Environment Variables]] — full \`.env\` reference
- [[Operations/Google OAuth]] — Sign in with Google + Gmail/Calendar

> Generated from the maya-unified codebase. Last updated: 2026-07-04.
`)

write("getting-started/installation.md", `---
title: Installation
tags: [getting-started, install]
---

# Installation

Maya Unified ships as a Python monorepo with a single root virtual environment.

## Choose your platform

| Platform | Guide |
|----------|-------|
| Windows 10/11 | [[Getting Started/Windows]] |
| NixOS / Linux (dev) | [[Getting Started/NixOS]] |

Shared prerequisites: [[Getting Started/Prerequisites]].

## Minimal path (Windows)

\`\`\`powershell
git clone https://github.com/System-Nebula/maya-unified.git
cd maya-unified
setup_windows.bat
copy .env.example .env
winget install Gyan.FFmpeg
launch.bat
\`\`\`

\`setup_windows.bat\` creates \`.venv\` at the **repo root**, installs PyTorch (CUDA 12.8 wheels), and \`pip install -e .\`.

## After install

1. Start LM Studio (or configure [[Voice Runtime/LLM]] provider).
2. Open http://localhost:8090 and sign in at [[Operations/Operator Auth]].
3. Copy bundled examples on first launch — see [[Getting Started/Bundled Examples]].

## Database (optional)

Platform features and operator auth require PostgreSQL. Run migrations:

\`\`\`bash
cd packages/maya-db
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/maya_public \\
  uv run alembic upgrade head
\`\`\`

See [[Configuration/Environment Variables]] for \`DATABASE_URL\` and auth settings.
`)

write("getting-started/windows.md", `---
title: Windows Setup
tags: [getting-started, windows]
---

# Windows Setup

Primary development target for Maya Unified.

## Steps

\`\`\`powershell
git clone https://github.com/System-Nebula/maya-unified.git
cd maya-unified
setup_windows.bat
copy .env.example .env
winget install Gyan.FFmpeg
launch.bat
\`\`\`

\`launch.bat\` invokes \`python launch.py\`, which delegates to [[Apps/Launch]] → [[Apps/Unified Gateway]].

## Manual install

\`\`\`bat
py -3.11 -m venv .venv
.venv\\Scripts\\activate
pip install "torch>=2.7.0" torchaudio --index-url https://download.pytorch.org/whl/cu128
pip install -e ".[mcp,otel]"
\`\`\`

## LM Studio

1. Download an instruct model in LM Studio.
2. Start the local server on \`:1234\`.
3. Set model id in **Settings → Reasoning** (dashboard) or \`VA_LLM_MODEL\` in \`.env\`.

## Tips

- Use **headphones** to reduce false barge-in during voice sessions.
- Prefer repo paths **without spaces**.
- If TTS fails, Maya starts in degraded mode — set \`VA_TTS_ENABLED=0\` to skip synthesis entirely.
`)

write("getting-started/nixos.md", `---
title: NixOS Setup
tags: [getting-started, nixos, linux]
---

# NixOS Setup

\`\`\`bash
git clone https://github.com/System-Nebula/maya-unified.git
cd maya-unified
nix develop          # or: direnv allow
make setup           # uv sync — torch cu124 + platform deps
cp .env.example .env
./launch.sh
\`\`\`

Enable NVIDIA and \`allowUnfree\` in \`configuration.nix\`. Stay inside \`nix develop\` for PortAudio, FFmpeg, and CUDA runtime libs.

## TTS optional

If \`faster-qwen3-tts\` or the model fails to load, Maya starts in degraded mode (text/Discord still work). Set \`VA_TTS_ENABLED=0\` to skip TTS. Run \`make tts-check\` after setup.

Optional extras:

\`\`\`bash
uv sync --extra dev --extra mcp --extra otel
\`\`\`
`)

write("getting-started/prerequisites.md", `---
title: Prerequisites
tags: [getting-started]
---

# Prerequisites

| Requirement | Notes |
|-------------|-------|
| Python 3.11–3.12 | 3.13+ not supported |
| NVIDIA GPU | Strongly recommended for STT/TTS |
| FFmpeg | Discord / YouTube playback (\`winget install Gyan.FFmpeg\`) |
| LM Studio | OpenAI-compatible API on \`:1234\` (default LLM path) |
| PostgreSQL | Required for operator auth, OAuth, platform APIs |
| Node.js ≥ 22 | Docs site build only (\`docs/\`) |

## Voice pipeline deps

Installed via \`setup_windows.bat\` or \`make setup\`:

- \`faster-whisper\` — STT
- \`faster-qwen3-tts\` — streaming TTS
- PyTorch with CUDA wheels

\`launch.py\` checks for voice deps and prints setup guidance if missing.
`)

write("getting-started/quickstart.md", `---
title: Quick Start
tags: [getting-started]
---

# Quick Start

Five-minute path to a working voice session.

## 1. Install

Follow [[Getting Started/Windows]] or [[Getting Started/NixOS]].

## 2. Configure LLM

\`\`\`env
VA_LLM_BASE_URL=http://localhost:1234/v1
VA_LLM_MODEL=local-model
VA_LLM_API_KEY=lm-studio
\`\`\`

Start LM Studio's local server before launching Maya.

## 3. Launch

\`\`\`bash
python launch.py
# or launch.bat / ./launch.sh
\`\`\`

Open http://localhost:8090 → sign in (\`admin\` / \`admin\` by default).

## 4. Talk

1. Grant microphone permission in the browser.
2. Press **Push to talk** or enable always-on VAD in Settings.
3. Watch the dashboard EQ and chat panel for responses.

## 5. Explore

| URL | Purpose |
|-----|---------|
| \`/\` | Dashboard — EQ, chat, tools |
| \`/memory\` | Memory explorer |
| \`/settings\` | Voice config + operator account |
| \`/docs\` | OpenAPI |

Next: [[Architecture/Overview]] and [[Voice Runtime/Agent Orchestrator]].
`)

write("getting-started/bundled-examples.md", `---
title: Bundled Examples
tags: [getting-started, examples]
---

# Bundled Examples

On first start, Maya copies shipped assets from \`examples/\` into your local runtime:

| Asset | Source | Destination |
|-------|--------|-------------|
| Demo voice clip | \`examples/voices/ref.wav\` + \`ref.txt\` | \`packages/voice-runtime/voices/\` |
| Personalities | \`examples/personalities/personalities.json\` | \`data/personalities.json\` |
| Starter skills | \`examples/skills/*.md\` | \`data/skills/\` |

Default personalities: **Maya-sama**, **Professor Mari**, **Call Center Scammer**.

Tools (Discord, web, memory, MCP) ship as code in \`packages/voice-runtime/tools/\` — enable them in **Settings**.

See [[Configuration/Personalities]] and [[Configuration/Skills]].
`)

// Architecture
write("architecture/overview.md", `---
title: Architecture Overview
tags: [architecture]
---

# Architecture Overview

Maya Unified combines a **local voice runtime** with an **operator dashboard** and optional **platform services** behind one FastAPI gateway.

\`\`\`mermaid
flowchart LR
  Browser --> Gateway
  Discord --> Gateway
  Gateway --> VoiceHub
  VoiceHub --> Agent
  Agent --> STT
  Agent --> LLM
  Agent --> TTS
  Gateway --> Dashboard
  Gateway --> Platform
  Platform --> DB[(PostgreSQL)]
\`\`\`

## Architectural layers

| Layer | Components |
|-------|------------|
| Entry | [[Apps/Launch]], [[Apps/Unified Gateway]] |
| Voice | [[Voice Runtime/Agent Orchestrator]], [[Services/Voice Hub]] |
| Applications | [[Apps/Dashboard]], [[Platform/Maya Gateway]] |
| Domain packages | [[Packages/Overview]] |
| Services | [[Services/Overview]] |
| Operations | [[Operations/Deployment]], [[Operations/Operator Auth]] |

## Request paths

- **HTML dashboard** — auth middleware redirects unauthenticated users to \`/login\`.
- **Voice WebSocket/API** — \`/api/voice/*\` requires operator session.
- **Platform APIs** — mounted when maya-gateway stack is enabled.

See [[Architecture/Request Pipeline]] and [[Architecture/Launch Flow]].
`)

write("architecture/repo-map.md", `---
title: Repository Map
tags: [architecture]
---

# Repository Map

\`\`\`
maya-unified/
├── launch.py                 # Single entrypoint
├── apps/
│   ├── gateway/              # Unified FastAPI (voice + dashboard APIs)
│   ├── dashboard/            # Static web UI
│   ├── maya-gateway/         # Platform routes (arena, discover, …)
│   ├── maya-bot/             # Full Discord /imagine bot
│   └── maya-ingest/          # Prefect feed ingest worker
├── packages/
│   ├── voice-runtime/        # STT, TTS, agent, tools, memory
│   ├── maya-contracts/       # Shared API types
│   ├── maya-db/              # SQLAlchemy models + Alembic
│   └── maya-*/               # feeds, research, image, graph, …
├── services/
│   ├── voice/hub.py          # VoiceHub bridge
│   ├── auth/                 # Operator sessions
│   ├── settings/             # Effective settings store
│   └── integrations/google/  # OAuth + Gmail/Calendar
├── examples/                 # Bundled voice clip, personalities, skills
├── data/                     # Runtime state (gitignored)
└── docs/                     # This documentation site (Quartz 5)
\`\`\`

Runtime state lives in \`data/\`. Voice reference clips default to \`packages/voice-runtime/voices/\`.
`)

write("architecture/layers.md", `---
title: Architectural Layers
tags: [architecture]
---

# Architectural Layers

The codebase organizes into ten layers (from knowledge-graph analysis):

1. **Entry & bootstrap** — \`launch.py\`, path setup, env loading
2. **Gateway & HTTP** — \`apps/gateway/\`, middleware, route registration
3. **Voice runtime** — \`packages/voice-runtime/\` agent loop
4. **Voice services** — \`services/voice/\` hub, inference locks, migration
5. **Dashboard & static UI** — \`apps/dashboard/\`
6. **Platform apps** — \`apps/maya-gateway/\`, bot, ingest
7. **Domain packages** — contracts, db, research, image, feeds, graph
8. **Cross-cutting services** — auth, settings, integrations
9. **Infrastructure** — ComfyUI, Docker, Nix
10. **Tests & tooling** — e2e, scripts, docs

Each layer has dedicated pages under [[Architecture/Overview]], [[Voice Runtime/Agent Orchestrator]], [[Platform/Maya Gateway]], and [[Packages/Overview]].
`)

write("architecture/launch-flow.md", `---
title: Launch Flow
tags: [architecture, launch]
aliases: [launch.py]
---

# Launch Flow

\`launch.py\` is the single entrypoint for Maya Unified.

\`\`\`mermaid
sequenceDiagram
  participant User
  participant Launch as launch.py
  participant Paths as services.paths
  participant Env as env_loader
  participant GW as apps.gateway.main

  User->>Launch: python launch.py
  Launch->>Paths: setup_paths()
  Launch->>Env: load_env_files(.env)
  Launch->>Launch: _check_voice_deps()
  Launch->>GW: run()
  GW->>User: http://localhost:8090
\`\`\`

## Key steps

1. **Path setup** — \`services.paths.setup_paths()\` adds repo root and \`packages/voice-runtime\` to \`sys.path\`.
2. **Env loading** — root \`.env\` plus legacy \`packages/voice-runtime/.env\`.
3. **Voice dep check** — warns if \`faster_whisper\` / \`faster_qwen3_tts\` missing (degraded TTS).
4. **Gateway** — \`apps.gateway.main.run()\` starts Uvicorn on \`PORT\` (default 8090).

See [[Apps/Launch]] and [[Apps/Unified Gateway]] for implementation detail.
`)

write("architecture/request-pipeline.md", `---
title: Request & Turn Pipeline
tags: [architecture, voice-runtime]
---

# Request & Turn Pipeline

## HTTP / dashboard

\`apps/gateway/main.py\` applies auth middleware:

- **Guarded HTML** — \`/\`, \`/memory\`, \`/settings\`, \`/admin\`, \`/rooms\` require operator session.
- **Open paths** — \`/login\`, \`/static\`, \`/docs\`, \`/health\`, guest room APIs.
- **Protected APIs** — \`/api/voice/*\`, \`/api/operators/*\`, \`/api/admin/*\` return 401 without session.

## Voice turn pipeline

\`\`\`
mic → VAD → faster-whisper (STT)
    → LLM (+ tools/MCP) via packages/voice-runtime/llm.py
    → sentence chunker → Qwen3-TTS (streaming) → speakers
    ↘ Discord / memory persistence / observability spans
\`\`\`

Orchestrated by [[Voice Runtime/Agent Orchestrator]] through [[Services/Voice Hub]], which wraps the legacy \`server.Hub\` with per-operator context and settings.

## Barge-in

When the user speaks during TTS playback, VAD triggers barge-in — see [[Voice Runtime/VAD and Barge-in]].
`)

write("architecture/voice-hub.md", `---
title: Voice Hub Bridge
tags: [architecture, voice-hub]
---

# Voice Hub Bridge

\`services/voice/hub.py\` implements **VoiceHub** — the bridge between the unified gateway and \`packages/voice-runtime/server.py\`.

## Responsibilities

- **Per-operator context** — isolated data dirs via \`services/operator_voice/paths\`
- **Settings application** — merges dashboard settings into runtime \`config\`
- **Voice lease** — single active voice session coordination
- **Room support** — multi-participant voice rooms
- **LLM hot-swap** — \`swap_agent_llm\` when provider changes in Settings
- **Data migration** — one-time copy from legacy \`qwen3-voice-agent/data\`

## Integration

\`apps/gateway/voice_routes.py\` registers agent WebSocket and REST endpoints against the hub singleton.

Related: [[Services/Voice Hub]], [[Voice Runtime/Agent Orchestrator]].
`)

// Voice runtime
const voicePages = {
  "voice-runtime/index.md": `---
title: Voice Runtime
tags: [voice-runtime]
---

# Voice Runtime

\`packages/voice-runtime/\` contains the local streaming voice assistant: STT, LLM, TTS, tools, memory, and optional Discord/VTuber integrations.

> **Unified layout:** In maya-unified, the voice server is **not** started via standalone \`server.py\` on \`:7861\` by default. Instead, [[Services/Voice Hub]] embeds the agent behind [[Apps/Unified Gateway]] on \`:8090\`.

## Pipeline

\`\`\`
mic → VAD → faster-whisper → LLM (+ tools) → Qwen3-TTS → speakers
\`\`\`

## Topics

- [[Voice Runtime/Agent Orchestrator]]
- [[Voice Runtime/STT Pipeline]]
- [[Voice Runtime/LLM]]
- [[Voice Runtime/TTS Pipeline]]
- [[Voice Runtime/VAD and Barge-in]]
- [[Voice Runtime/Memory and Tools]]
`,
  "voice-runtime/agent.md": `---
title: Agent Orchestrator
tags: [voice-runtime, agent]
---

# Agent Orchestrator

The agent loop coordinates STT, LLM streaming, tool calls, TTS chunking, and memory writes for each conversational turn.

## Flow

1. **Listen** — VAD detects speech; audio buffered for STT.
2. **Transcribe** — [[Voice Runtime/STT Pipeline]] returns text.
3. **Reason** — [[Voice Runtime/LLM]] streams tokens; tools invoked via orchestrator when \`VA_LLM_ORCHESTRATOR=1\`.
4. **Speak** — sentences fed to [[Voice Runtime/TTS Pipeline]] for low-latency playback.
5. **Persist** — [[Voice Runtime/Memory and Tools]] layers updated.

## Configuration

Key env vars: \`VA_LLM_ORCHESTRATOR\`, \`VA_WEB_TOOLS_ENABLED\`, \`VA_LLM_MAX_TOKENS\`, \`VA_LLM_TEMPERATURE\`.

Dashboard **Settings → Reasoning** overrides provider, model, and WebLLM mode without restart when supported by [[Services/Voice Hub]].
`,
  "voice-runtime/stt.md": `---
title: STT Pipeline
tags: [voice-runtime, stt]
---

# STT Pipeline

Speech-to-text uses **faster-whisper** on the local GPU.

## Behavior

- Model size configurable via settings / env (default balances speed vs accuracy).
- Partial transcripts may appear in the dashboard during long utterances.
- STT runs under inference lock shared with TTS to avoid GPU contention — see \`services/voice/inference.py\`.

## Related settings

| Variable | Purpose |
|----------|---------|
| \`VA_LOG_LEVEL\` | Pipeline logging verbosity |
| Mic device | Selected in dashboard Settings |

Upstream reference: \`packages/voice-runtime/\` transcription modules (adapted paths in unified repo).
`,
  "voice-runtime/llm.md": `---
title: LLM Streaming Client
tags: [voice-runtime, llm]
aliases: [llm.py]
---

# LLM Streaming Client

\`packages/voice-runtime/llm.py\` implements the streaming chat client used by the agent.

## Providers

| Provider | Config | Notes |
|----------|--------|-------|
| LM Studio | \`VA_LLM_PROVIDER=lm_studio\` | Default local path, \`:1234/v1\` |
| LiteLLM SDK | \`VA_LLM_PROVIDER=litellm\` | OpenRouter, hosted models |
| WebLLM | Browser WebGPU | No server env; dashboard-only |

## Key environment variables

\`\`\`env
VA_LLM_BASE_URL=http://localhost:1234/v1
VA_LLM_MODEL=local-model
VA_LLM_API_KEY=lm-studio
VA_LLM_TEMPERATURE=0.6
VA_LLM_MAX_TOKENS=220
VA_LLM_ORCHESTRATOR=1
\`\`\`

## Reasoning models

- Set \`VA_LLM_REASONING_EFFORT=none\` for Gemma/reasoning models or spoken replies may be empty.
- Qwen3 hidden thinking disabled via \`VA_LLM_DISABLE_THINKING=1\`.

Unified gateway hot-swaps clients through \`services/llm/provider.py\` when settings change.
`,
  "voice-runtime/tts.md": `---
title: TTS Pipeline
tags: [voice-runtime, tts]
---

# TTS Pipeline

Text-to-speech uses **[faster-qwen3-tts](https://github.com/andimarafioti/faster-qwen3-tts)** with streaming sentence chunking for low latency.

## Voice cloning

Reference clips live in \`packages/voice-runtime/voices/\`. The bundled \`ref.wav\` from [[Getting Started/Bundled Examples]] is copied on first launch.

## Degraded mode

If TTS deps fail to import, \`launch.py\` warns and Maya continues with text-only output. Set \`VA_TTS_ENABLED=0\` to skip TTS initialization entirely.

## Output

- \`VA_OUTPUT_VOLUME\` — master gain
- Dashboard EQ visualization reflects live audio levels
`,
  "voice-runtime/vad-barge-in.md": `---
title: VAD and Barge-in
tags: [voice-runtime, vad]
---

# VAD and Barge-in

Voice Activity Detection (VAD) gates when audio is sent to STT. **Barge-in** cancels in-progress TTS when the user starts speaking.

## Best practices

- Use **headphones** to prevent the mic from picking up speaker output (false barge-in).
- Tune VAD sensitivity in dashboard Settings for your room noise profile.
- Push-to-talk mode bypasses always-on VAD when preferred.
`,
  "voice-runtime/memory-tools.md": `---
title: Memory and Tools
tags: [voice-runtime, memory, tools]
---

# Memory and Tools

## Memory layers

Maya supports layered memory (short-term conversation, long-term facts, character/personality context). Explore stored memories at \`/memory\` in the dashboard.

Settings sections \`memory\` and \`tools\` trigger hub reload when changed — see \`_RELOAD_SECTIONS\` in [[Services/Voice Hub]].

## Built-in tools

Located in \`packages/voice-runtime/tools/\`:

- Web search (\`VA_WEB_TOOLS_ENABLED=1\`)
- Discord messaging and voice controls
- MCP servers (\`pip install -e ".[mcp]"\`)

## Skills

Markdown skill files in \`data/skills/\` extend agent behavior — see [[Configuration/Skills]].
`,
}

for (const [rel, body] of Object.entries(voicePages)) write(rel, body)

// Apps
write("apps/index.md", `---
title: Applications
tags: [apps]
---

# Applications

| App | Path | Role |
|-----|------|------|
| Unified Gateway | \`apps/gateway/\` | [[Apps/Unified Gateway]] |
| Dashboard | \`apps/dashboard/\` | [[Apps/Dashboard]] |
| Launch | \`launch.py\` | [[Apps/Launch]] |
| Platform Gateway | \`apps/maya-gateway/\` | [[Platform/Maya Gateway]] |
| Discord Bot | \`apps/maya-bot/\` | [[Platform/Maya Bot]] |
| Ingest Worker | \`apps/maya-ingest/\` | [[Platform/Maya Ingest]] |
`)

write("apps/unified-gateway.md", `---
title: Unified Gateway
tags: [apps, gateway]
aliases: [apps/gateway/main.py]
---

# Unified Gateway

\`apps/gateway/main.py\` is the FastAPI application for Maya Unified.

## Routers

| Router | Purpose |
|--------|---------|
| \`auth_routes\` | Operator login/logout |
| \`platform_auth_routes\` | Google OAuth login |
| \`google_integrations_routes\` | Gmail/Calendar connect |
| \`settings_routes\` | Voice + operator settings API |
| \`voice_routes\` | Agent WebSocket and control |
| \`room_routes\` | Multi-user voice rooms |
| \`admin_routes\` | Operator management |

## Static assets

Dashboard static files mounted under \`/static\` and \`/dashboard\`. OpenAPI at \`/docs\`.

## Lifespan

\`apps/gateway/lifespan.py\` initializes VoiceHub, seeds default operator, runs migrations hooks.

See [[Architecture/Request Pipeline]] for auth middleware behavior.
`)

write("apps/dashboard.md", `---
title: Operator Dashboard
tags: [apps, dashboard]
---

# Operator Dashboard

Static web UI in \`apps/dashboard/\` served by the unified gateway.

## Routes

| URL | Purpose |
|-----|---------|
| \`/\` | Main dashboard — EQ, chat, push-to-talk |
| \`/memory\` | Memory explorer |
| \`/settings\` | Account + voice configuration |
| \`/login\` | Operator sign-in |
| \`/setup\` | First-run admin creation |
| \`/admin/users\` | Operator management (admin role) |

User menu → **Settings** for account, reasoning provider, Discord, integrations.

Frontend modules include \`apps/dashboard/js/mayaIntegrations.js\` for Google connect UI.
`)

write("apps/launch.md", `---
title: Launch Entrypoint
tags: [apps, launch]
aliases: [launch.py]
---

# Launch Entrypoint

\`launch.py\` at the repo root:

\`\`\`python
from services.paths import setup_paths, VOICE_RUNTIME
setup_paths()
load_env_files(ROOT / ".env", VOICE_RUNTIME / ".env")
from apps.gateway.main import run
run()
\`\`\`

## Platform wrappers

- **Windows** — \`launch.bat\`
- **Unix** — \`launch.sh\`

Warns if not running inside project \`.venv\` when voice deps are expected.

See [[Architecture/Launch Flow]].
`)

// Platform
const platformPages = {
  "platform/maya-gateway.md": `---
title: Maya Gateway
tags: [platform, maya-gateway]
---

# Maya Gateway

\`apps/maya-gateway/\` exposes platform APIs: arena, discover, research orchestration, and image generation when the full stack is enabled.

Requires PostgreSQL (\`DATABASE_URL\`) and domain packages under \`packages/maya-*\`.

Mounted into the unified gateway when platform routes are registered. See [[Packages/Overview]] for shared contracts and persistence.
`,
  "platform/maya-bot.md": `---
title: Maya Bot
tags: [platform, discord]
---

# Maya Bot

Full Discord \`/imagine\` bot in \`apps/maya-bot/\`.

\`\`\`bash
uv run maya-bot
\`\`\`

Separate from in-agent Discord tools in [[Voice Runtime/Memory and Tools]] — this is the standalone image/command bot.
`,
  "platform/maya-ingest.md": `---
title: Maya Ingest
tags: [platform, ingest]
---

# Maya Ingest

\`apps/maya-ingest/\` runs Prefect flows for feed ingestion into the platform datastore.

Pairs with [[Packages/Maya Feeds]] adapters. Optional — enable when running discover/feed features.
`,
  "platform/discord-shim.md": `---
title: Discord Integration
tags: [platform, discord]
---

# Discord Integration

Two Discord surfaces:

1. **Voice runtime tools** — \`VA_DISCORD_*\` env vars, configured in Settings → Discord
2. **Maya Bot** — [[Platform/Maya Bot]] for \`/imagine\` and platform commands

Common env:

\`\`\`env
VA_DISCORD_ENABLED=0
VA_DISCORD_TOKEN=
VA_DISCORD_GUILD_ID=
VA_DISCORD_AUTO_REPLY=1
\`\`\`
`,
}

for (const [rel, body] of Object.entries(platformPages)) write(rel, body)

// Packages
write("packages/index.md", `---
title: Packages Overview
tags: [packages]
aliases: [Packages/Overview]
---

# Domain Packages

| Package | Doc |
|---------|-----|
| \`maya-contracts\` | [[Packages/Maya Contracts]] |
| \`maya-db\` | [[Packages/Maya DB]] |
| \`maya-research\` | [[Packages/Maya Research]] |
| \`maya-image\` | [[Packages/Maya Image]] |
| \`maya-feeds\` | [[Packages/Maya Feeds]] |
| \`maya-graph\` | [[Packages/Maya Graph]] |
| \`voice-runtime\` | [[Voice Runtime]] |

All packages are editable installs from root \`pyproject.toml\`.
`)

const pkgPages = {
  "packages/maya-contracts.md": `---
title: Maya Contracts
tags: [packages, contracts]
---

# Maya Contracts

\`packages/maya-contracts/\` — shared Pydantic types and API schemas consumed by gateway, bot, and frontend SDK.

Keeps request/response shapes consistent across [[Platform/Maya Gateway]] and dashboard clients.
`,
  "packages/maya-db.md": `---
title: Maya DB
tags: [packages, database]
---

# Maya DB

\`packages/maya-db/\` — SQLAlchemy models, Alembic migrations, Postgres schema.

## Tables include

- \`operator_users\` — dashboard operators
- \`oauth_pkce_states\`, \`operator_google_identities\`, \`google_connections\` — [[Operations/Google OAuth]]
- Platform entities for arena, feeds, research jobs

\`\`\`bash
cd packages/maya-db
DATABASE_URL=postgresql+asyncpg://... uv run alembic upgrade head
\`\`\`
`,
  "packages/maya-research.md": `---
title: Maya Research
tags: [packages, research]
---

# Maya Research

\`packages/maya-research/\` — LangGraph-based research orchestration for deep-dive queries.

Invoked from platform routes when research features are enabled. Depends on [[Packages/Maya Contracts]] and [[Packages/Maya DB]].
`,
  "packages/maya-image.md": `---
title: Maya Image
tags: [packages, image]
---

# Maya Image

\`packages/maya-image/\` — image generation providers and output paths.

\`\`\`env
COMFYUI_API_URL=http://localhost:3000
MAYA_IMAGE_ROOT=./data/outputs/maya-image
\`\`\`

See [[Operations/ComfyUI]] for local ComfyUI infrastructure.
`,
  "packages/maya-feeds.md": `---
title: Maya Feeds
tags: [packages, feeds]
---

# Maya Feeds

\`packages/maya-feeds/\` — feed adapters and normalization for discover/ingest pipelines.

Used by [[Platform/Maya Ingest]] and platform discover APIs.
`,
  "packages/maya-graph.md": `---
title: Maya Graph
tags: [packages, graph]
---

# Maya Graph

\`packages/maya-graph/\` — graph storage and query helpers for linked platform content.

Integrates with research and discover features in [[Platform/Maya Gateway]].
`,
}

for (const [rel, body] of Object.entries(pkgPages)) write(rel, body)

// Services
write("services/index.md", `---
title: Services Overview
tags: [services]
aliases: [Services/Overview]
---

# Services

Cross-cutting modules under \`services/\`:

| Service | Doc |
|---------|-----|
| Voice Hub | [[Services/Voice Hub]] |
| Operator Auth | [[Services/Operator Auth]] |
| Settings Store | [[Services/Settings Store]] |
| Google Integrations | [[Services/Google Integrations]] |
`)

write("services/voice-hub.md", `---
title: Voice Hub Service
tags: [services, voice-hub]
---

# Voice Hub Service

\`services/voice/hub.py\` — see [[Architecture/Voice Hub Bridge]] for architecture.

Exports the singleton hub used by \`apps/gateway/voice_routes.py\`. Handles operator scoping, settings reload, and LLM provider swaps.
`)

write("services/operator-auth.md", `---
title: Operator Auth Service
tags: [services, auth]
---

# Operator Auth Service

\`services/auth/\` — operator sessions, password hashing, role checks.

- Cookie: \`maya_op_session\` signed with \`SESSION_SECRET\`
- Store: \`operator_users\` in PostgreSQL
- Deps: \`services/auth/deps.py\` for FastAPI dependencies

See [[Operations/Operator Auth]] for operator-facing documentation.
`)

write("services/settings-store.md", `---
title: Settings Store
tags: [services, settings]
---

# Settings Store

\`services/settings/store.py\` — loads effective voice settings (global + operator overrides), applies to runtime \`config\`, persists dashboard changes.

\`seed_env_defaults()\` maps \`.env\` values into the settings document on first run.
`)

write("services/google-integrations.md", `---
title: Google Integrations Service
tags: [services, google, oauth]
---

# Google Integrations Service

\`services/integrations/google/\`:

| Module | Role |
|--------|------|
| \`config.py\` | Env vars, dynamic redirect URI |
| \`oauth.py\` | PKCE generation and token exchange |
| \`scopes.py\` | Permission groups → Google scopes |
| \`token_store.py\` | Refresh tokens on disk |
| \`service.py\` | Gmail + Calendar reads |

Gateway routes in \`apps/gateway/platform_auth_routes.py\` and \`google_integrations_routes.py\`.

Full setup: [[Operations/Google OAuth]].
`)

// Configuration
write("configuration/env-vars.md", `---
title: Environment Variables
tags: [configuration, env]
---

# Environment Variables

Copy \`.env.example\` to \`.env\` at the repo root. Shell exports are overridden by \`.env\` on startup.

## Voice runtime

| Variable | Default | Purpose |
|----------|---------|---------|
| \`VA_LLM_BASE_URL\` | \`http://localhost:1234/v1\` | OpenAI-compatible LLM endpoint |
| \`VA_LLM_MODEL\` | \`local-model\` | Model id |
| \`VA_LLM_API_KEY\` | \`lm-studio\` | API key |
| \`VA_LLM_TEMPERATURE\` | \`0.6\` | Sampling temperature |
| \`VA_LLM_MAX_TOKENS\` | \`220\` | Max reply tokens |
| \`VA_LLM_ORCHESTRATOR\` | \`1\` | Tool orchestration |
| \`VA_WEB_TOOLS_ENABLED\` | \`1\` | Web search tools |
| \`VA_OUTPUT_VOLUME\` | \`1.0\` | TTS gain |
| \`VA_TTS_ENABLED\` | \`1\` | Set \`0\` to skip TTS |
| \`VA_DISCORD_ENABLED\` | \`0\` | Discord tools |
| \`VA_OTEL_ENABLED\` | \`0\` | OpenTelemetry |

## Platform & auth

| Variable | Purpose |
|----------|---------|
| \`PORT\` | Gateway port (8090) |
| \`DATABASE_URL\` | PostgreSQL async URL |
| \`SESSION_SECRET\` | Operator session signing |
| \`SESSION_COOKIE_SECURE\` | \`1\` behind HTTPS |
| \`OPERATOR_DEFAULT_USERNAME\` | Seed admin username |
| \`OPERATOR_DEFAULT_PASSWORD\` | Seed admin password |

## Google OAuth

See [[Operations/Google OAuth]] and \`.env.example\` for \`GOOGLE_CLIENT_ID\`, redirect URIs, and \`MAYA_GOOGLE_TOKEN_DIR\`.

Full index: [[Reference/Environment Index]].
`)

write("configuration/personalities.md", `---
title: Personalities
tags: [configuration, personalities]
---

# Personalities

Character definitions live in \`data/personalities.json\` (seeded from [[Getting Started/Bundled Examples]]).

Each personality controls system prompt tone, voice selection, and optional card metadata (SillyTavern-style).

Edit via dashboard or directly in JSON; restart or reload settings as needed.
`)

write("configuration/skills.md", `---
title: Skills
tags: [configuration, skills]
---

# Skills

Markdown files in \`data/skills/\` extend agent capabilities with structured instructions.

Starter skills copied from \`examples/skills/\` on first launch. Enable corresponding tools in **Settings** for skills that require web, Discord, or MCP access.
`)

// Operations
write("operations/operator-auth.md", `---
title: Operator Auth
tags: [operations, auth]
---

# Operator Auth

The unified dashboard uses **local operator accounts** — separate from platform invite/OAuth users when the full maya-gateway stack is enabled.

| What | Where |
|------|-------|
| Credentials + roles | PostgreSQL \`operator_users\` |
| Sessions | Signed cookie \`maya_op_session\` |
| Preferences | Browser \`localStorage\` (not synced) |

**Default:** \`admin\` / \`admin\` auto-created when no operators exist. Change password in Settings → Account.

**Roles:** \`admin\` (manage operators), \`operator\` (dashboard only).

Protected APIs return **401** without valid session. See [[Services/Operator Auth]].
`)

write("operations/google-oauth.md", `---
title: Google OAuth
tags: [operations, oauth, google]
source: app-integrations-google-oauth.md
---

# Google OAuth

Maya Unified supports two separate Google OAuth flows:

1. **Platform sign-in** — authenticate an operator via Google (login page).
2. **App integration connect** — link Gmail/Calendar scopes for an already-signed-in operator (Settings → Integrations).

Both flows use PKCE, persist short-lived state in Postgres, and honor dynamic redirect URIs derived from the browser host when \`MAYA_OAUTH_DYNAMIC_REDIRECT=1\`.

## Architecture

\`\`\`
Login flow
  GET /api/platform/auth/login/google
    → store oauth_pkce_states (verifier, redirect_uri, flow=login)
    → redirect to Google with code_challenge (S256)
  GET /auth/google/callback  (legacy path; also /api/platform/auth/callback/google)
    → exchange code + stored verifier for tokens
    → link operator_google_identities or match by email/username
    → set maya_op_session cookie

Connect flow
  GET /api/integrations/google/connect?permissions=mailbox_read,calendar_read
    → require operator session
    → store oauth_pkce_states (flow=connect, operator_id)
  GET /api/integrations/google/callback
    → exchange code, write refresh token to disk
    → upsert google_connections row
    → redirect to /settings?tab=integrations
\`\`\`

### Code layout

| Path | Purpose |
|------|---------|
| \`services/integrations/google/config.py\` | Env vars, dynamic redirect URI, Console checklist |
| \`services/integrations/google/oauth.py\` | PKCE pair generation, Flow helpers, token exchange |
| \`services/integrations/google/scopes.py\` | Permission groups → Google scopes |
| \`services/integrations/google/token_store.py\` | Refresh tokens on disk (\`MAYA_GOOGLE_TOKEN_DIR\`) |
| \`services/integrations/google/service.py\` | Gmail inbox + Calendar event reads |
| \`apps/gateway/platform_auth_routes.py\` | Platform login + callback |
| \`apps/gateway/google_integrations_routes.py\` | Connect, status, disconnect, service APIs |
| \`apps/dashboard/js/mayaIntegrations.js\` | Settings → Integrations UI |

### Database tables

| Table | Purpose |
|-------|---------|
| \`oauth_pkce_states\` | Short-lived PKCE state, verifier, redirect_uri, flow |
| \`operator_google_identities\` | Links Google account to operator for sign-in |
| \`google_connections\` | Connected integration metadata (tokens on disk) |

Run migrations:

\`\`\`bash
cd packages/maya-db
DATABASE_URL=postgresql+asyncpg://maya:maya@localhost:5433/maya \\
  python -m alembic upgrade head
\`\`\`

## Google Cloud Console setup

1. Create or select a **Web application** OAuth client.
2. Copy **Client ID** and **Client secret** into \`.env\`.
3. Register **Authorized redirect URIs** (all six for local dev):

\`\`\`
http://localhost:8090/auth/google/callback
http://localhost:8090/api/platform/auth/callback/google
http://localhost:8090/api/integrations/google/callback
http://127.0.0.1:8090/auth/google/callback
http://127.0.0.1:8090/api/platform/auth/callback/google
http://127.0.0.1:8090/api/integrations/google/callback
\`\`\`

4. Register **Authorized JavaScript origins**:

\`\`\`
http://localhost:8090
http://127.0.0.1:8090
\`\`\`

5. Delete any empty URI rows before clicking **Save**.

Print the live checklist:

\`\`\`bash
python scripts/verify_google_oauth.py
\`\`\`

## Environment variables

\`\`\`env
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
MAYA_APP_BASE_URL=http://localhost:8090
MAYA_OAUTH_DYNAMIC_REDIRECT=1
GOOGLE_LOGIN_REDIRECT_URI=http://localhost:8090/auth/google/callback
GOOGLE_CONNECT_REDIRECT_URI=http://localhost:8090/api/integrations/google/callback
MAYA_GOOGLE_TOKEN_DIR=.data/google-tokens
\`\`\`

## Permission groups

| Permission | Google scopes |
|------------|---------------|
| \`mailbox_read\` | \`gmail.readonly\` |
| \`mailbox_send\` | \`gmail.compose\`, \`gmail.send\`, \`gmail.modify\` |
| \`calendar_read\` | \`calendar.readonly\` |
| \`calendar_write\` | \`calendar\` |

## Service APIs

| Endpoint | Purpose |
|----------|---------|
| \`GET /api/integrations/google/status\` | Connection state |
| \`GET /api/integrations/google/connect\` | Start connect OAuth |
| \`DELETE /api/integrations/google\` | Disconnect |
| \`GET /api/services/email/inboxes\` | Inbox threads |
| \`GET /api/services/calendar/events\` | Calendar events |

## Troubleshooting

### redirect_uri_mismatch

Run \`python scripts/verify_google_oauth.py\` and match \`Live redirect_uri\` to Google Console exactly.

### Invalid code verifier

Start a fresh OAuth flow — authorization codes are single-use.

### OAuth tables missing (503)

Run Alembic migrations in \`packages/maya-db\`.
`)

write("operations/deployment.md", `---
title: Deployment
tags: [operations, deployment]
---

# Deployment

## Local development

\`\`\`bash
python launch.py
\`\`\`

Default port \`8090\`. Set \`SESSION_COOKIE_SECURE=1\` when serving over HTTPS.

## Production checklist

- Change \`SESSION_SECRET\` and default operator password
- PostgreSQL with migrations applied
- Register production OAuth redirect URIs ([[Operations/Google OAuth]])
- GPU instance for voice STT/TTS workloads
- Reverse proxy (TLS termination) in front of Uvicorn

## Documentation site

This docs site builds to GitHub Pages — see \`docs/README.md\` and \`.github/workflows/deploy-docs.yml\`.
`)

write("operations/optional-services.md", `---
title: Optional Services
tags: [operations]
---

# Optional Services

| Feature | How |
|---------|-----|
| Discord voice/music | Settings → Discord → bot token |
| Platform arena/discover | \`uv sync\` + Postgres |
| \`/imagine\` Discord bot | \`uv run maya-bot\` — [[Platform/Maya Bot]] |
| Legacy voice WebUI | \`python packages/voice-runtime/server.py\` → \`:7861\` |
| ComfyUI image gen | [[Operations/ComfyUI]] |
| Feed ingest | [[Platform/Maya Ingest]] |
`)

write("operations/comfyui.md", `---
title: ComfyUI Infrastructure
tags: [operations, comfyui, image]
---

# ComfyUI Infrastructure

Local ComfyUI stack under \`infra/comfyui/\` for [[Packages/Maya Image]] generation.

\`\`\`env
COMFYUI_API_URL=http://localhost:3000
MAYA_IMAGE_ROOT=./data/outputs/maya-image
\`\`\`

See \`infra/comfyui/README.md\` in the repository for compose setup and Makefile targets.
`)

// Development
write("development/monorepo.md", `---
title: Monorepo Conventions
tags: [development]
---

# Monorepo Conventions

| Change type | Location |
|-------------|----------|
| Unified gateway / auth | \`apps/\`, \`services/\` |
| Voice engine | \`packages/voice-runtime/\` |
| Platform APIs | \`packages/maya-*\`, \`apps/maya-gateway/\` |

\`\`\`bash
pip install -e .
python launch.py
\`\`\`

Single \`pyproject.toml\` at root. Runtime data in \`data/\` only.

## Data migration

Legacy standalone \`qwen3-voice-agent/data\` migrates once to \`data/\` (marker: \`data/.migrated-from-qwen3\`).
`)

write("development/testing.md", `---
title: Testing
tags: [development, testing]
---

# Testing

## Unit tests

\`\`\`bash
make test
# or: uv run pytest
\`\`\`

## E2E (Playwright)

\`\`\`bash
make e2e-install
make e2e-test
\`\`\`

See \`tests/e2e/README.md\` for browser test scope and environment setup.

## TTS verification

\`\`\`bash
make tts-check
\`\`\`
`)

// Reference
write("reference/api.md", `---
title: HTTP API Reference
tags: [reference, api]
---

# HTTP API Reference

Interactive OpenAPI docs ship with the gateway:

| URL | Format |
|-----|--------|
| \`/docs\` | Swagger UI |
| \`/redoc\` | ReDoc |
| \`/openapi.json\` | Raw schema |

## Protected prefixes

- \`/api/voice/*\` — agent control and streaming
- \`/api/operators/*\` — operator management
- \`/api/admin/*\` — admin APIs
- \`/api/integrations/google/*\` — Google connect (session required)

Guest room APIs under \`/api/rooms/*\` have separate guest token rules — see [[Architecture/Request Pipeline]].
`)

write("reference/env-index.md", `---
title: Environment Index
tags: [reference, env]
aliases: [Environment Index]
---

# Environment Index

Quick lookup — detailed descriptions in [[Configuration/Environment Variables]].

| Prefix | Domain |
|--------|--------|
| \`VA_*\` | Voice runtime |
| \`SESSION_*\`, \`OPERATOR_*\` | Operator auth |
| \`GOOGLE_*\`, \`MAYA_OAUTH_*\`, \`MAYA_GOOGLE_*\` | Google OAuth |
| \`DATABASE_URL\` | PostgreSQL |
| \`COMFYUI_*\`, \`MAYA_IMAGE_*\` | Image generation |
| \`PORT\` | Gateway listen port |
| \`DISCORD_TOKEN\` | Platform bot (maya-bot) |
`)

write("reference/glossary.md", `---
title: Glossary
tags: [reference]
---

# Glossary

| Term | Meaning |
|------|---------|
| **Operator** | Dashboard user with local account (\`operator_users\`) |
| **VoiceHub** | Unified bridge to voice-runtime \`Hub\` |
| **Barge-in** | User speech cancels active TTS playback |
| **PKCE** | OAuth proof key for Google login/connect flows |
| **Platform** | Optional arena/discover/research/image APIs |
| **Personality** | Character profile (prompt + voice) |
| **Skill** | Markdown instruction file extending agent behavior |
| **Degraded mode** | Gateway runs without TTS when deps missing |
`)

console.log(`Wrote documentation to ${ROOT}`)
