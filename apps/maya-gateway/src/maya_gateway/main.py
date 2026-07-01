"""Maya Public Gateway — FastAPI entrypoint."""

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from obs_client import configure_logging

from maya_gateway.routes import arena, discover, discover_inbox, feeds, follow, health, intel, music, music_query, notifications, registry, research, voice

log = logging.getLogger("maya-gateway")


def _include_workspace_imagine() -> None:
    """Mount Imagine routes from in-repo maya_image, falling back to ~/Workspace."""
    try:
        from maya_image.api import router as imagine_router

        app.include_router(imagine_router)
        log.info("imagine_router mounted from maya_image")
        return
    except Exception as exc:
        log.debug("in-repo imagine_router unavailable: %s", exc)

    workspace = Path(os.environ.get("WORKSPACE_ROOT", Path.home() / "Workspace")).resolve()
    for p in (str(workspace), str(workspace / "src")):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        from src.maya.api.imagine import router as imagine_router  # type: ignore[import-not-found]

        app.include_router(imagine_router)
        log.info("imagine_router mounted from workspace %s", workspace)
    except Exception as exc:  # noqa: BLE001
        log.warning("imagine_router unavailable: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging("maya-gateway", log_level="INFO")
    yield


app = FastAPI(
    title="Maya Gateway",
    description="Public API surface for Arena, Feed, Registry, and Image services.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# API routes (all prefixed /api/* except docs)
app.include_router(health.router)
app.include_router(arena.router)
app.include_router(music.router)
app.include_router(music_query.router)
app.include_router(registry.router)
app.include_router(feeds.router)
app.include_router(intel.router)
app.include_router(follow.router)
app.include_router(notifications.router)
app.include_router(discover.router)
app.include_router(discover_inbox.router)
app.include_router(research.router)
app.include_router(voice.router)

# Imagine /gateway/imagine — canonical backend from ~/Workspace
_include_workspace_imagine()

static_dir = Path(__file__).with_name("static").resolve()

# Generated image artifacts (ComfyUI outputs)
_image_root = Path(
    os.environ.get(
        "MAYA_IMAGE_ROOT",
        Path(os.environ.get("WORKSPACE_ROOT", Path.home() / "Workspace")) / "data/outputs/maya-image",
    )
).resolve()
_image_root.mkdir(parents=True, exist_ok=True)
app.mount("/imagine-outputs", StaticFiles(directory=str(_image_root)), name="imagine-outputs")

# Gateway static assets (Alpine imagine UI)
_gateway_static = static_dir / "gateway"
if _gateway_static.is_dir():
    app.mount("/static/gateway", StaticFiles(directory=str(_gateway_static)), name="gateway-static")


@app.get("/")
async def root():
    return FileResponse(static_dir / "index.html")


@app.get("/{path:path}")
async def spa_catchall(path: str):
    # Never shadow API, docs, gateway, or image output routes
    if path.startswith(
        ("api/", "docs", "redoc", "openapi.json", "gateway/", "imagine-outputs/", "static/")
    ):
        raise HTTPException(status_code=404, detail="Not found")
    target = static_dir / path
    if target.exists() and target.is_file():
        return FileResponse(target)
    return FileResponse(static_dir / "index.html")


def run() -> None:
    import uvicorn

    uvicorn.run(
        "maya_gateway.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        reload=os.getenv("ENV", "production") == "development",
    )
