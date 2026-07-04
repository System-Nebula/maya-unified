---
title: Deployment
tags: [operations, deployment]
aliases: [Operations/Deployment]
---

# Deployment

Maya Unified ships primarily as a **single-process FastAPI application** (`apps.gateway.main:app`) launched via `python launch.py` or platform-specific scripts (`launch.bat`, `./launch.sh`). This guide covers local development defaults, production hardening, and optional co-processes (Discord bot, ingest workers, ComfyUI).

## Process topology

```mermaid
flowchart TB
    subgraph required["Required for voice dashboard"]
        GW["Unified gateway :8090"]
        LLM["LM Studio / LLM API"]
        GPU["NVIDIA GPU — STT/TTS"]
    end

    subgraph optional["Optional co-processes"]
        PG[(PostgreSQL)]
        COMFY[ComfyUI :3000]
        BOT[maya-bot]
        ING[maya-ingest worker]
    end

    GW --> LLM
    GW --> GPU
    GW --> PG
    BOT --> PG
    BOT --> COMFY
    ING --> PG
    GW -.-> COMFY
```

## Local development

```bash
python launch.py
# or: launch.bat / ./launch.sh
```

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8090` | Uvicorn listen port |
| `ENV` | `production` | Set `development` for auto-reload |
| `HOST` | `0.0.0.0` | Bind address (via uvicorn in `main.run()`) |

Development reload excludes `packages/voice-runtime/*` to avoid reloading heavy TTS weights on every file save.

Health check: `GET /health` → `{"ok": true, "service": "maya-unified"}`.

## Production checklist

### Secrets and auth

- [ ] Set strong `SESSION_SECRET` (never use `dev-insecure-change-me`)
- [ ] Change default operator password after [[Operations/Operator Auth]] setup
- [ ] Set `SESSION_COOKIE_SECURE=1` when TLS terminates at reverse proxy
- [ ] Restrict Postgres credentials; never expose `DATABASE_URL` publicly

### Database

- [ ] Run `alembic upgrade head` in `packages/maya-db` against production Postgres
- [ ] Enable `pgvector` extension if using discover/research features
- [ ] Configure automated backups for operator and OAuth tables

### OAuth

- [ ] Register production redirect URIs in Google Cloud Console ([[Operations/Google OAuth]])
- [ ] Set `MAYA_APP_BASE_URL` to public HTTPS origin
- [ ] Run `python scripts/verify_google_oauth.py` against staging

### Voice workloads

- [ ] GPU instance with sufficient VRAM for Qwen TTS + Whisper models
- [ ] LM Studio or hosted LLM reachable from gateway network
- [ ] FFmpeg installed for Discord/YouTube audio paths

### Reverse proxy

Terminate TLS at nginx, Caddy, or cloud load balancer; proxy to Uvicorn:

```nginx
location / {
    proxy_pass http://127.0.0.1:8090;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    # SSE for /api/voice/agent/events
    proxy_buffering off;
    proxy_read_timeout 3600s;
}
```

Long-lived SSE streams require `proxy_buffering off` and extended read timeout.

### Optional services

- [ ] ComfyUI stack for image features ([[Operations/ComfyUI]])
- [ ] `uv run maya-bot` on stable host if using Discord arena ([[Platform/Maya Bot]])
- [ ] Prefect/agent for ingest ([[Platform/Maya Ingest]])

## Environment profile

Minimal voice-only (no Postgres):

```env
PORT=8090
VA_LLM_BASE_URL=http://localhost:1234/v1
```

Full unified (recommended):

```env
PORT=8090
SESSION_SECRET=<random-64-chars>
DATABASE_URL=postgresql+asyncpg://maya:***@db.internal:5432/maya
SESSION_COOKIE_SECURE=1
MAYA_APP_BASE_URL=https://maya.example.com
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
```

See [[Reference/Environment Index]] and [[Configuration/Environment Variables]].

## Documentation site

The Quartz docs under `docs/` build to GitHub Pages via `.github/workflows/deploy-docs.yml`. Documentation deployment is independent of gateway deployment — see `docs/README.md` for `npm` build steps.

## Monitoring

Optional OpenTelemetry via `pip install -e ".[otel]"` and `platform.otel_enabled` in settings. Voice observability hooks live in `packages/voice-runtime/observability.py` when OTEL packages present.

## Troubleshooting

**Port 8090 already in use after reload**

Uvicorn graceful shutdown timeout is 5s for SSE connections — wait or kill stale process.

**502 from proxy on SSE**

Increase proxy read timeout; disable buffering.

**Works on HTTP, breaks on HTTPS**

Enable `SESSION_COOKIE_SECURE=1` and verify Google OAuth redirect URIs use `https://`.

**Platform routes missing in prod**

Ensure `uv sync --all-packages` in build image; check logs for `mounted platform routes`.

## Related documentation

- [[Getting Started/Installation]] — first install
- [[Operations/Operator Auth]] — auth hardening
- [[Operations/Optional Services]] — co-process matrix
- [[Development/Monorepo Conventions]] — build layout
