---
title: Environment Index
tags: [reference, env]
aliases: [Environment Index, Reference/Environment Index]
---

# Environment Index

Quick lookup for environment variables across Maya Unified. Detailed descriptions and dashboard equivalents live in [[Configuration/Environment Variables]]; this page groups by domain for grep-friendly ops work.

Variables load from repo root `.env` and `packages/voice-runtime/.env` via `services/env_loader.py` at gateway startup.

## Gateway and process

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8090` | Uvicorn listen port |
| `ENV` | `production` | Set `development` for hot reload |
| `MAYA_APP_BASE_URL` | `http://localhost:8090` | Canonical public URL (OAuth) |

## Operator auth

| Variable | Default | Description |
|----------|---------|-------------|
| `SESSION_SECRET` | fallback insecure | HMAC secret for `maya_op_session` |
| `SESSION_SECRET_FALLBACK` | `dev-insecure-change-me` | Used when SESSION_SECRET empty |
| `SESSION_COOKIE_SECURE` | `0` | Set `1` behind HTTPS |
| `DATABASE_URL` | *(none)* | Postgres async DSN for operators |

Prefix `OPERATOR_*` may appear in legacy docs — prefer `SESSION_*` + `DATABASE_URL`.

## Voice runtime (`VA_*`)

| Variable | Default | Maps to settings section |
|----------|---------|--------------------------|
| `VA_LLM_BASE_URL` | `http://localhost:1234/v1` | `reasoning.base_url` |
| `VA_LLM_MODEL` | `local-model` | `reasoning.model` |
| `VA_LLM_API_KEY` | `lm-studio` | `reasoning.api_key` |
| `VA_TTS_ENABLED` | `1` | Skip TTS load when `0` |
| `VA_DISCORD_ENABLED` | `0` | `discord.enabled` |
| `VA_DISCORD_TOKEN` | | `discord.token` |
| `VA_DISCORD_GUILD_ID` | | `discord.guild_id` |
| `VA_DISCORD_AUTO_REPLY` | `1` | `discord.auto_reply` |

See [[Voice Runtime]] and `packages/voice-runtime/config.py` for extended `VA_*` list.

## Google OAuth

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_CLIENT_ID` | | OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | | OAuth client secret |
| `MAYA_OAUTH_DYNAMIC_REDIRECT` | `1` | Host-based redirect URIs |
| `GOOGLE_LOGIN_REDIRECT_URI` | localhost callback | Platform login callback |
| `GOOGLE_CONNECT_REDIRECT_URI` | localhost callback | Integrations callback |
| `MAYA_GOOGLE_TOKEN_DIR` | `.data/google-tokens` | Refresh token storage |

## Image / ComfyUI

| Variable | Default | Description |
|----------|---------|-------------|
| `COMFYUI_API_URL` | `http://localhost:3000` | comfyui-api base |
| `MAYA_IMAGE_ROOT` | `./data/outputs/maya-image` | Generated images |
| `MAYA_ARENA_PAIR` | seeded | Arena workflow pair |
| `MAYA_ARENA_SIZE` | `512x512` | Arena dimensions |
| `HF_TOKEN` | | Hugging Face downloads |
| `MAYA_ENABLE_HOSTED_PROVIDERS` | `0` | fal/Ideogram providers |

## Discord bot (maya-bot process)

| Variable | Default | Description |
|----------|---------|-------------|
| `DISCORD_TOKEN` | | Bot token for `uv run maya-bot` |
| `TEST_GUILD_ID` | | Instant slash command sync |
| `IMAGINE_SKIP_PORTAL_LINK` | `1` | Self-host portal bypass |
| `MAYA_DEV_PORTAL_USER_ID` | | Synthetic user id |

Distinct from in-agent `VA_DISCORD_*` — see [[Platform/Discord Integration]].

## Platform and observability

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | | Shared Postgres for platform + auth |
| OTEL exporter vars | | When `pip install -e ".[otel]"` |

## Research / ingest (optional)

| Variable | Description |
|----------|-------------|
| `SEARXNG_URL` | Meta-search for research tool |
| Prefect env | Ingest worker configuration |

## Prefix summary table

| Prefix | Domain |
|--------|--------|
| `VA_*` | Voice runtime |
| `SESSION_*` | Operator session cookies |
| `GOOGLE_*`, `MAYA_OAUTH_*`, `MAYA_GOOGLE_*` | Google OAuth |
| `DATABASE_URL` | PostgreSQL |
| `COMFYUI_*`, `MAYA_IMAGE_*`, `MAYA_ARENA_*` | Image generation |
| `DISCORD_*` | Standalone maya-bot |
| `PORT`, `ENV` | Gateway process |

## Troubleshooting

**Env change not reflected**

Restart gateway — most vars read at startup. Settings JSON overrides many `VA_*` fields after `seed_env_defaults()` via dashboard.

**Two .env files conflict**

Both root and `packages/voice-runtime/.env` load — later file wins for duplicate keys per loader order in `main.py`.

**Secrets in git**

Never commit `.env` — use `.env.example` as template only.

## Related documentation

- [[Configuration/Environment Variables]] — full reference
- [[Services/Settings Store]] — JSON persistence vs env
- [[Operations/Deployment]] — production env profile
