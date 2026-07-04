---
title: Maya Bot
tags: [platform, discord, bot, arena]
aliases: [Platform/Maya Bot]
---

# Maya Bot

`apps/maya-bot/` is a **standalone Discord application** that exposes Maya's image arena through slash commands — primarily `/imagine` with blind A/B workflow battles, ELO ranking, and ComfyUI-backed rendering. It runs as a separate process from the unified voice dashboard and is distinct from in-agent Discord tools configured in Settings → Discord ([[Platform/Discord Integration]]).

## Quick start

```bash
# From repo root after full workspace sync
uv sync --all-packages

export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/maya
cd packages/maya-db && uv run alembic upgrade head && cd ../..

# Start ComfyUI stack — see Operations/ComfyUI
cp .env.example .env
# Edit DISCORD_TOKEN, DATABASE_URL, COMFYUI_API_URL

uv run maya-bot
```

In Discord (bot invited with `applications.commands` scope):

```
/imagine prompt:"a cat astronaut" mode:Arena
```

Voters use A / B / Tie buttons; ratings update via ELO in `arena_candidates`.

## Architecture

```mermaid
sequenceDiagram
    participant U as Discord user
    participant B as maya-bot
    participant MI as maya-image
    participant C as ComfyUI :3000
    participant DB as PostgreSQL

    U->>B: /imagine mode:Arena
    B->>DB: pick arena_candidates (2 workflows)
    B->>MI: render prompt × 2 workflows
    MI->>C: workflow jobs
    C-->>MI: PNG outputs
    MI-->>B: image paths
    B-->>U: A/B embed + vote buttons
    U->>B: vote A
    B->>DB: arena_votes + ELO update
```

## Package layout

```
apps/maya-bot/
├── pyproject.toml
├── README.md
└── src/maya_bot/
    ├── main.py           # bot entry + cog loading
    ├── launcher.py       # uv run maya-bot script target
    └── cogs/
        └── imagine.py    # /imagine slash command
```

Console entry: `uv run maya-bot` (defined in `pyproject.toml` scripts).

## Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `DISCORD_TOKEN` | *(required)* | Bot token from Discord Developer Portal |
| `DATABASE_URL` | *(required)* | Postgres DSN (bot may use sync driver internally) |
| `COMFYUI_API_URL` | `http://localhost:3000` | comfyui-api base URL |
| `HF_TOKEN` | *(optional)* | Hugging Face downloads for weight scripts |
| `IMAGINE_SKIP_PORTAL_LINK` | `1` | Skip portal OAuth for self-hosters |
| `MAYA_DEV_PORTAL_USER_ID` | `local-dev` | Synthetic user when portal bypass on |
| `MAYA_ARENA_PAIR` | seeded pair | Comma-separated workflow names |
| `MAYA_ARENA_SIZE` | `512x512` | Normalized arena panel dimensions |
| `MAYA_IMAGE_ROOT` | `./data/outputs/maya-image` | Generated image storage |
| `TEST_GUILD_ID` | *(optional)* | Instant slash command sync to one guild |
| `MAYA_ENABLE_HOSTED_PROVIDERS` | `0` | Enable fal/Ideogram with API keys |

## How the arena works

1. **`/imagine mode:Arena`** selects two workflows from `image_workflows` where `is_arena_candidate=true` (seeded: Z-Image Turbo vs Krea 2 Turbo).
2. Both images render at `MAYA_ARENA_SIZE`, cover-cropped for side-by-side display.
3. Votes record in `arena_votes` with weighted tallies.
4. ELO ratings on `arena_candidates` update when a battle completes.

Tune opponents with `MAYA_ARENA_PAIR=z-image-turbo-t2i,krea2-turbo-t2i`.

Non-arena modes may generate single images through [[Packages/Maya Image]] providers — see cog implementation in `cogs/imagine.py`.

## vs voice-runtime Discord tools

| Surface | Process | Capabilities |
|---------|---------|--------------|
| **Maya Bot** | `uv run maya-bot` | Slash commands, arena, platform DB |
| **Voice Discord tools** | Inside unified gateway | Voice channel join, music, auto-reply, optional imagine via settings |

Configure voice Discord via `VA_DISCORD_*` env vars or Settings → Discord (`discord.token`, `discord.guild_id`). These paths do not require the maya-bot process.

## Troubleshooting

**Slash commands missing**

Set `TEST_GUILD_ID` to your server snowflake for instant guild sync, or wait up to an hour for global command propagation.

**Portal link message on /imagine**

Set `IMAGINE_SKIP_PORTAL_LINK=1` and `MAYA_DEV_PORTAL_USER_ID=local-dev`.

**Comfy 404 / timeout**

Confirm `COMFYUI_API_URL` and run weight fetch Makefile targets in `infra/comfyui/`.

**DB errors on vote**

Run `alembic upgrade head` in `packages/maya-db`.

**Bot online but images blank**

Check `MAYA_IMAGE_ROOT` permissions and GPU availability on the ComfyUI host.

## Related documentation

- [[Operations/ComfyUI]] — local GPU stack
- [[Packages/Maya Image]] — generation orchestration
- [[Platform/Discord Integration]] — voice agent Discord path
- [[Operations/Optional Services]] — when to run the bot
