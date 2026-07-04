---
title: Unified Gateway
tags: [apps, gateway]
aliases: [apps/gateway/main.py]
source: apps/gateway/main.py
---

# Unified Gateway

**`apps/gateway/main.py`** is the FastAPI application that binds Maya Unified into a single HTTP server on port **8090** (configurable via `PORT`). It is the only application Uvicorn runs when you execute `launch.py`.

Everything operators touch—dashboard pages, voice APIs, settings, OAuth callbacks, optional platform routes—mounts here.

## Application structure

```python
app = FastAPI(
    title="Maya Unified",
    lifespan=lifespan,  # apps/gateway/lifespan.py
    docs_url="/docs",
)
```

Startup side effects (data migration, agent load, operator seed) live in **`lifespan`**, not import time—see [[Architecture/Launch Flow]].

## Auth middleware

`_auth_guard` runs on every request before route handlers:

- **Protected JSON APIs** → 401 if no valid operator session
- **Guarded HTML** → redirect `/login` or `/setup`
- **Banned operators** → 403 API / login redirect with flag

Operator cookie: **`maya_op_session`** (signed with `SESSION_SECRET`).

Detailed path rules: [[Architecture/Request Pipeline]].

## Router mounting order

| Router | Prefix / paths | Source |
|--------|----------------|--------|
| `auth_router` | `/api/auth/*` | Operator login/logout/me |
| `admin_router` | `/api/admin/*` | Admin APIs |
| `platform_auth_router` | `/api/platform/auth/*` | Google login |
| `google_integrations_router` | `/api/integrations/google/*` | Gmail/Calendar connect |
| `mp_voice_router` | `/api/voice/*` (SDK subset) | `maya_gateway.routes.voice` (optional) |
| Platform routers | `/api/arena`, discover, … | `_mount_platform_routes()` |
| `settings_router` | Settings persistence | Dashboard voice config |
| `room_router` | `/api/rooms/*` | Multi-user voice rooms |
| `register_agent_routes` | `/api/voice/agent/*` | Core agent control |

Platform routers import inside `_mount_platform_routes()` with try/except—missing deps log warning, voice still works.

## HTML page routes

Static dashboard pages served via explicit `@app.get` handlers (not SPA router):

| Path | File | Purpose |
|------|------|---------|
| `/` | `conversation.html` | Main voice dashboard |
| `/memory` | `memory.html` | Memory explorer |
| `/settings` | `settings.html` | Account + voice config |
| `/login` | `login.html` | Operator sign-in |
| `/setup` | `setup.html` | First admin creation |
| `/admin/users` | `admin-users.html` | Operator management |
| `/rooms` | `rooms.html` | Room list |
| `/room/{slug}` | `room.html` | Guest room UI |
| `/experimental` | `experimental.html` | Legacy standalone WebUI info |

## Static mounts

```python
app.mount("/sdk", StaticFiles(...))       # maya_gateway voice SDK
app.mount("/dashboard", StaticFiles(...)) # JS/CSS assets
```

Dashboard HTML references scripts under `/dashboard/js/`.

## Health & OpenAPI

- **`GET /health`** → `{"ok": true, "service": "maya-unified"}`
- **`/docs`**, **`/redoc`**, **`/openapi.json`** — full API schema

Use OpenAPI for authoritative route list; narrative grouping in [[Reference/HTTP API Reference]].

## Uvicorn runner

```python
def run():
    uvicorn.run(
        "apps.gateway.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8090")),
        reload=os.getenv("ENV") == "development",
        reload_excludes=["packages/voice-runtime/*"],
        timeout_graceful_shutdown=5,
    )
```

Dev reload skips voice-runtime file changes to avoid reloading multi-GB TTS weights on every save.

## Extension points

| Want to add… | Where |
|--------------|-------|
| New REST API | New router in `apps/gateway/` or `apps/maya-gateway/` |
| New dashboard page | HTML in `apps/dashboard/` + route in `main.py` |
| Auth rule | `_path_needs_api_auth`, `_GUARDED_PREFIXES` |
| Startup hook | `lifespan.py` |

## Related

- [[Architecture/Overview]]
- [[Apps/Dashboard]]
- [[Services/Voice Hub Service]]
