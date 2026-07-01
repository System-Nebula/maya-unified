"""Maya Unified gateway — voice agent + platform APIs."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from services.paths import GATEWAY_SRC, setup_paths  # noqa: E402

setup_paths()

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from apps.gateway.lifespan import lifespan  # noqa: E402
from apps.gateway.settings_routes import router as settings_router  # noqa: E402
from apps.gateway.voice_routes import register_agent_routes  # noqa: E402

log = logging.getLogger("maya-unified.gateway")

app = FastAPI(
    title="Maya Unified",
    description="Maya voice agent + platform gateway + dashboard",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# --- voice SDK routes (settings/defaults, demo turn) ----------------------------
try:
    from maya_gateway.routes.voice import router as mp_voice_router

    app.include_router(mp_voice_router)
    log.info("mounted voice SDK /api/voice routes")
except Exception as exc:  # noqa: BLE001
    log.warning("voice SDK routes unavailable: %s", exc)

# --- platform routes (optional — uv sync for full stack) ------------------------
def _mount_platform_routes() -> None:
    try:
        from maya_gateway.routes import (
            arena,
            discover,
            discover_inbox,
            feeds,
            follow,
            health,
            intel,
            music,
            music_query,
            notifications,
            registry,
            research,
        )

        for r in (
            health,
            arena,
            music,
            music_query,
            registry,
            feeds,
            intel,
            follow,
            notifications,
            discover,
            discover_inbox,
            research,
        ):
            app.include_router(r.router)
        log.info("mounted platform routes")
    except Exception as exc:  # noqa: BLE001
        log.warning("platform routes unavailable (run uv sync): %s", exc)


_mount_platform_routes()

app.include_router(settings_router)
register_agent_routes(app)

# --- static: voice SDK ----------------------------------------------------------
_sdk_dir = GATEWAY_SRC / "maya_gateway" / "static" / "sdk"
_dashboard_dir = _ROOT / "apps" / "dashboard"

if _sdk_dir.is_dir():
    app.mount("/sdk", StaticFiles(directory=str(_sdk_dir)), name="voice-sdk")

if _dashboard_dir.is_dir():
    app.mount("/dashboard", StaticFiles(directory=str(_dashboard_dir)), name="dashboard-static")


@app.get("/")
def root():
    """Main dashboard — voice conversation + pipeline."""
    page = _dashboard_dir / "conversation.html"
    if page.is_file():
        return FileResponse(page)
    return RedirectResponse(url="/settings")


@app.get("/conversation")
def conversation_redirect():
    return RedirectResponse(url="/")


@app.get("/panel")
def panel_redirect():
    return RedirectResponse(url="/settings")


@app.get("/experimental")
def experimental_standalone_info():
    """Legacy standalone voice WebUI — not used by the unified dashboard."""
    page = _dashboard_dir / "experimental.html"
    if page.is_file():
        return FileResponse(page)
    raise HTTPException(404, "experimental.html not found")


@app.get("/memory")
def memory_page():
    page = _dashboard_dir / "memory.html"
    if page.is_file():
        return FileResponse(page)
    raise HTTPException(404, "memory.html not found")


@app.get("/settings")
def settings_page():
    page = _dashboard_dir / "settings.html"
    if page.is_file():
        return FileResponse(page)
    raise HTTPException(404, "settings.html not found")


@app.get("/health")
def unified_health():
    return {"ok": True, "service": "maya-unified"}


def run() -> None:
    import uvicorn

    from apps.gateway.asyncio_compat import install_logging_filter

    install_logging_filter()
    port = int(os.getenv("PORT", "8090"))
    uvicorn.run(
        "apps.gateway.main:app",
        host="0.0.0.0",
        port=port,
        reload=os.getenv("ENV", "production") == "development",
    )
