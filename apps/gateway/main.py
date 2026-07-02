"""Maya Unified gateway — voice agent + platform APIs."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _load_env_files() -> None:
    """Load repo .env before maya_db reads DATABASE_URL (same as launch.py)."""
    from services.paths import VOICE_RUNTIME  # noqa: PLC0415

    for env_file in (_ROOT / ".env", VOICE_RUNTIME / ".env"):
        if not env_file.is_file():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = val.strip().strip('"').strip("'")


_load_env_files()

from services.paths import GATEWAY_SRC, setup_paths  # noqa: E402

setup_paths()

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from apps.gateway.auth_routes import router as auth_router  # noqa: E402
from apps.gateway.lifespan import lifespan  # noqa: E402
from apps.gateway.settings_routes import router as settings_router  # noqa: E402
from apps.gateway.voice_routes import register_agent_routes  # noqa: E402
from services.auth.deps import resolve_operator_from_token  # noqa: E402
from services.auth.operator_store import any_operators_exist, get_db_session  # noqa: E402
from services.auth.session import OPERATOR_SESSION_COOKIE, verify_operator_session  # noqa: E402

log = logging.getLogger("maya-unified.gateway")

app = FastAPI(
    title="Maya Unified",
    description="Maya voice agent + platform gateway + dashboard",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# Auth guard middleware — redirect unauthenticated HTML; 401 JSON for protected APIs
# ---------------------------------------------------------------------------
_GUARDED_PREFIXES = ("/", "/memory", "/settings", "/panel", "/admin")
_OPEN_PREFIXES = (
    "/login", "/setup", "/static", "/sdk", "/dashboard", "/docs", "/redoc",
    "/openapi", "/health", "/favicon",
)
_API_PROTECTED_PREFIXES = ("/api/voice/agent", "/api/voice/settings")
_API_AUTH_OPEN = ("/api/auth/login", "/api/auth/logout", "/api/auth/me")


def _path_needs_api_auth(path: str, method: str) -> bool:
    if any(path == p or path.startswith(p + "/") for p in _API_AUTH_OPEN):
        return False
    if path.startswith("/api/operators"):
        if method == "POST" and path == "/api/operators":
            return False
        return True
    return any(path.startswith(p) for p in _API_PROTECTED_PREFIXES)


async def _attach_operator(request: Request):
    """Resolve operator from cookie and attach to request.state."""
    request.state.operator = None
    token = request.cookies.get(OPERATOR_SESSION_COOKIE)
    if not token:
        return None
    payload = verify_operator_session(token)
    if not payload or not payload.get("operator_id"):
        return None
    try:
        async for session in get_db_session():
            op = await resolve_operator_from_token(session, token)
            request.state.operator = op
            return op
    except Exception:
        request.state.operator = None
        return None


@app.middleware("http")
async def _auth_guard(request: Request, call_next):
    path = request.url.path
    method = request.method

    if path.startswith("/api") and _path_needs_api_auth(path, method):
        op = await _attach_operator(request)
        if op is None:
            return JSONResponse({"detail": "not authenticated"}, status_code=401)
        return await call_next(request)

    if any(path.startswith(p) for p in _OPEN_PREFIXES):
        return await call_next(request)
    if path.startswith("/api"):
        return await call_next(request)
    if not any(path == p or path.startswith(p + "/") for p in _GUARDED_PREFIXES):
        return await call_next(request)

    op = await _attach_operator(request)
    if op is not None:
        return await call_next(request)

    try:
        async for session in get_db_session():
            needs_setup = not await any_operators_exist(session)
    except Exception:
        needs_setup = False
    if needs_setup:
        return RedirectResponse(url="/setup")
    return RedirectResponse(url=f"/login?next={request.url.path}")

# --- operator auth (dashboard) — mount before other /api/auth routes -------------
app.include_router(auth_router)

# --- voice SDK routes (settings/defaults, demo turn) -----------------------------
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


@app.get("/login")
def login_page():
    """Operator login page."""
    page = _dashboard_dir / "login.html"
    if page.is_file():
        return FileResponse(page)
    raise HTTPException(404, "login.html not found")


@app.get("/setup")
def setup_page():
    """First-run admin account creation."""
    page = _dashboard_dir / "setup.html"
    if page.is_file():
        return FileResponse(page)
    raise HTTPException(404, "setup.html not found")


@app.get("/profile")
def profile_redirect():
    """Legacy profile URL — account lives under Settings."""
    return RedirectResponse(url="/settings?tab=account", status_code=302)


@app.get("/admin/users")
def admin_users_page():
    """Admin operator management panel."""
    page = _dashboard_dir / "admin-users.html"
    if page.is_file():
        return FileResponse(page)
    raise HTTPException(404, "admin-users.html not found")


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
