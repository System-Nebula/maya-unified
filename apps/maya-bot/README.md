# Maya Discord bot — `/imagine` + ComfyUI arena

Self-host the Maya image arena: blind A/B battles between local ComfyUI workflows with ELO ranking.

## Prerequisites

- **Python 3.11+** and [uv](https://docs.astral.sh/uv/)
- **PostgreSQL 15+** (local Docker or managed)
- **NVIDIA GPU** + [ComfyUI stack](../../infra/comfyui/README.md) on port 3000
- A **Discord bot token** ([Developer Portal](https://discord.com/developers/applications))

## Quick start

```bash
git clone https://github.com/System-Nebula/maya-public.git
cd maya-public
uv sync --all-packages

# Postgres (example — adjust credentials)
export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/maya

# Apply migrations (arena + image_workflows + seeds)
cd packages/maya-db && uv run alembic upgrade head && cd ../..

# ComfyUI — see infra/comfyui/README.md
# Then configure env:
cp .env.example .env
# Edit: DISCORD_TOKEN, DATABASE_URL, COMFYUI_API_URL, HF_TOKEN, MAYA_DEV_PORTAL_USER_ID

uv run maya-bot
```

In Discord (after inviting the bot with `applications.commands` scope):

```
/imagine prompt:"a cat astronaut" mode:Arena
```

Vote with the A / B / Tie buttons. Ratings update via ELO in `arena_candidates`.

## Environment

| Variable | Purpose |
|----------|---------|
| `DISCORD_TOKEN` | Bot token (required) |
| `DATABASE_URL` | Postgres DSN (async URL ok — bot uses sync driver internally) |
| `COMFYUI_API_URL` | comfyui-api base URL (default `http://localhost:3000`) |
| `HF_TOKEN` | Hugging Face downloads for weight fetch scripts |
| `IMAGINE_SKIP_PORTAL_LINK` | Default `1` — skip portal OAuth for self-hosters |
| `MAYA_DEV_PORTAL_USER_ID` | Synthetic portal user id when bypass is on |
| `MAYA_ARENA_PAIR` | Comma-separated workflow names for arena opponents |
| `MAYA_ARENA_SIZE` | Normalized arena panel size (default `512x512`) |
| `MAYA_IMAGE_ROOT` | Local path for generated images |
| `TEST_GUILD_ID` | Optional — sync slash commands to one guild instantly |

Optional hosted providers (Ideogram API, fal.ai): set `MAYA_ENABLE_HOSTED_PROVIDERS=1` and provider API keys.

## How the arena works

1. **`/imagine mode:Arena`** picks two workflows from `image_workflows` where `is_arena_candidate=true` (seeded: Z-Image Turbo vs Krea 2 Turbo).
2. Both images render at the same resolution (`MAYA_ARENA_SIZE`, cover-cropped side-by-side).
3. Voters pick A, B, or Tie — votes are recorded in `arena_votes` with weighted tallies.
4. ELO ratings on `arena_candidates` update when a battle completes.

Tune pairing with `MAYA_ARENA_PAIR=z-image-turbo-t2i,krea2-turbo-t2i`.

## Troubleshooting

- **Slash commands missing**: set `TEST_GUILD_ID` to your server id, or wait up to an hour for global sync.
- **Portal link message**: set `IMAGINE_SKIP_PORTAL_LINK=1` and `MAYA_DEV_PORTAL_USER_ID=local-dev`.
- **Comfy 404 / timeout**: confirm `COMFYUI_API_URL` and weights (`make fetch-zimage`, `make fetch-krea2`).
- **DB errors**: run `alembic upgrade head` in `packages/maya-db`.
