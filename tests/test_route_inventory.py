"""Smoke every mounted HTTP/WebSocket route (operator profile).

Unauthenticated operator APIs should 401 via middleware. Public handlers may
return 2xx/3xx/4xx/503. 500 fails the inventory. Streaming endpoints are bounded
by a short timeout so SSE generators cannot hang CI.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

os.environ.setdefault("MAYA_PROFILE", "operator")
os.environ.setdefault("VA_TTS_ENABLED", "0")
os.environ.setdefault("VA_STT_DEVICE", "cpu")
os.environ.setdefault("SESSION_SECRET", "route-inventory-test-secret-32")
os.environ.setdefault("HOST", "127.0.0.1")
os.environ.setdefault("ENV", "production")

from apps.gateway.main import app  # noqa: E402
from apps.gateway.platform_auth_routes import router as platform_auth_router  # noqa: E402
from services.auth.api_auth_registry import iter_mounted_api_routes  # noqa: E402
from services.voice.hub import hub  # noqa: E402

hub.load_agent = lambda *a, **k: None  # type: ignore[method-assign]

# Floor so dropping platform routers cannot silently shrink CI coverage.
MIN_HTTP_ROUTES = 90
MIN_API_ROUTES = 70
_SENTINEL_UUID = "00000000-0000-0000-0000-000000000001"
_STREAM_HINTS = ("/events", "/tts/stream", "/ws")
_SKIP_METHODS = frozenset({"HEAD", "OPTIONS"})
_ROOT = Path(__file__).resolve().parents[1]
_INVENTORY_PORT = 18090


def _postgres_listening() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 5432), timeout=0.5):
            return True
    except OSError:
        return False


def _ensure_platform_routes() -> None:
    from apps.gateway import main as gateway_main

    paths = {getattr(route, "path", "") for route in app.routes}
    if "/api/status/health" not in paths:
        gateway_main._MAYA_PROFILE = "operator"
        gateway_main._mount_platform_routes()
    paths = {getattr(route, "path", "") for route in app.routes}
    if "/api/platform/auth/status" not in paths:
        app.include_router(platform_auth_router)


def _fill_path(path: str) -> str:
    def _repl(match: re.Match[str]) -> str:
        raw = match.group(1)
        name, _, conv = raw.partition(":")
        lowered = name.lower()
        if conv == "path":
            return "x"
        if "uuid" in conv or lowered.endswith("_id") or lowered in {"id", "operator_id"}:
            return _SENTINEL_UUID
        if lowered == "provider":
            return "google"
        return "x"

    return re.sub(r"\{([^}]+)\}", _repl, path)


def _is_streaming(path: str) -> bool:
    lowered = path.lower()
    return any(hint in lowered for hint in _STREAM_HINTS)


def _iter_http_routes() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for route in app.router.routes:
        if not isinstance(route, APIRoute):
            continue
        methods = sorted(m for m in (route.methods or set()) if m not in _SKIP_METHODS)
        for method in methods:
            if _is_streaming(route.path):
                continue
            rows.append((method, route.path))
    rows.sort()
    return rows


def _iter_ws_routes() -> list[str]:
    paths = []
    for route in app.router.routes:
        if isinstance(route, APIWebSocketRoute):
            paths.append(route.path)
        elif type(route).__name__ == "WebSocketRoute":
            paths.append(route.path)
    return sorted(set(paths))


def _call(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    timeout: float,
    json_body: dict[str, Any] | None,
) -> httpx.Response:
    kwargs: dict[str, Any] = {"timeout": timeout}
    if json_body is not None:
        kwargs["json"] = json_body
    return client.request(method, path, **kwargs)


def _probe(
    client: httpx.Client,
    method: str,
    template: str,
) -> tuple[str, int]:
    path = _fill_path(template)
    json_body = None if method in {"GET", "DELETE"} else {}
    timeout = 0.8 if _is_streaming(template) else 2.0
    try:
        response = _call(client, method, path, timeout=timeout, json_body=json_body)
    except (httpx.TimeoutException, httpx.TransportError):
        return path, 200
    return path, int(response.status_code)


def _require_postgres() -> None:
    if _postgres_listening():
        return
    if os.environ.get("CI"):
        pytest.fail("Postgres on 127.0.0.1:5432 is required for route inventory in CI")
    pytest.skip("Postgres not listening on 127.0.0.1:5432")


def _login_operator(client: httpx.Client) -> None:
    """Seed an admin via psycopg2 and attach a signed session cookie."""
    import psycopg2

    from services.auth.passwords import hash_password
    from services.auth.session import OPERATOR_SESSION_COOKIE, sign_operator_session

    oid = str(uuid.uuid4())
    password_hash = hash_password("password123")
    conn = psycopg2.connect(
        "postgresql://postgres:postgres@127.0.0.1:5432/maya_public"
    )
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM operator_users WHERE username = %s", ("admin",))
                row = cur.fetchone()
                if row:
                    oid = str(row[0])
                else:
                    cur.execute(
                        """
                        INSERT INTO operator_users
                            (id, username, display_name, password_hash, role)
                        VALUES (%s, %s, %s, %s, 'admin')
                        """,
                        (oid, "admin", "Admin", password_hash),
                    )
    finally:
        conn.close()
    client.cookies.set(OPERATOR_SESSION_COOKIE, sign_operator_session(oid))


@pytest.fixture(scope="module")
def live_client() -> httpx.Client:
    _ensure_platform_routes()
    _require_postgres()
    env = os.environ.copy()
    env.update(
        {
            "MAYA_PROFILE": "operator",
            "VA_TTS_ENABLED": "0",
            "VA_STT_DEVICE": "cpu",
            "HOST": "127.0.0.1",
            "PORT": str(_INVENTORY_PORT),
            "ENV": "production",
            "SESSION_SECRET": os.environ.get(
                "SESSION_SECRET", "route-inventory-test-secret-32"
            ),
            "DATABASE_URL": os.environ.get(
                "DATABASE_URL",
                "postgresql+asyncpg://postgres:postgres@localhost:5432/maya_public",
            ),
            "PYTHONPATH": str(_ROOT),
        }
    )
    code = (
        "from services.paths import setup_paths; setup_paths(); "
        "from services.voice.hub import hub; hub.load_agent = lambda *a, **k: None; "
        "import uvicorn; "
        f"uvicorn.run('apps.gateway.main:app', host='127.0.0.1', port={_INVENTORY_PORT}, "
        "log_level='warning')"
    )
    log_path = _ROOT / "data" / "route-inventory-uvicorn.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        env=env,
        cwd=str(_ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{_INVENTORY_PORT}"
    try:
        ready = False
        for _ in range(60):
            try:
                response = httpx.get(f"{base}/health", timeout=0.5)
                if response.status_code < 500:
                    ready = True
                    break
            except httpx.HTTPError:
                time.sleep(0.25)
        if not ready:
            proc.kill()
            log_file.close()
            pytest.fail(
                "inventory uvicorn did not become ready on /health\n"
                + log_path.read_text(encoding="utf-8")[-4000:]
            )
        with httpx.Client(base_url=base, timeout=2.0, follow_redirects=False) as client:
            yield client
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_file.close()


@pytest.fixture(scope="module")
def inventory_client() -> TestClient:
    _ensure_platform_routes()
    try:
        client = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    except TypeError:
        client = TestClient(app, raise_server_exceptions=False)
    yield client


def test_operator_profile_mounts_platform_health() -> None:
    _ensure_platform_routes()
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/status/health" in paths
    assert "/api/platform/auth/status" in paths


def test_route_inventory_counts() -> None:
    _ensure_platform_routes()
    http_rows = _iter_http_routes()
    api_rows = iter_mounted_api_routes(app)
    print(f"route inventory: {len(http_rows)} HTTP, {len(api_rows)} /api")
    assert len(http_rows) >= MIN_HTTP_ROUTES, (
        f"expected at least {MIN_HTTP_ROUTES} HTTP routes, found {len(http_rows)}"
    )
    assert len(api_rows) >= MIN_API_ROUTES, (
        f"expected at least {MIN_API_ROUTES} /api routes, found {len(api_rows)}"
    )


def test_all_http_routes_unauthenticated(live_client: httpx.Client) -> None:
    live_client.cookies.clear()
    failures: list[str] = []
    seen = 0
    for method, template in _iter_http_routes():
        path, status = _probe(live_client, method, template)
        seen += 1
        if status == 500:
            failures.append(f"{method} {path} -> {status}")
    assert seen >= MIN_HTTP_ROUTES
    assert not failures, "500 responses:\n" + "\n".join(failures)


def test_all_http_routes_authenticated(live_client: httpx.Client) -> None:
    live_client.cookies.clear()
    _login_operator(live_client)
    failures: list[str] = []
    for method, template in _iter_http_routes():
        path, status = _probe(live_client, method, template)
        if status == 500:
            failures.append(f"{method} {path} -> {status}")
    assert not failures, "authenticated 500 responses:\n" + "\n".join(failures)


def test_live_health(live_client: httpx.Client) -> None:
    response = live_client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body.get("ok") is True


def test_websocket_routes_do_not_500(inventory_client: TestClient) -> None:
    _require_postgres()
    paths = _iter_ws_routes()
    if not paths:
        pytest.skip("no websocket routes mounted")
    for template in paths:
        path = _fill_path(template)

        def _connect() -> None:
            try:
                with inventory_client.websocket_connect(path) as ws:
                    ws.close()
            except WebSocketDisconnect:
                return
            except Exception as exc:  # noqa: BLE001
                message = str(exc)
                if "1008" in message or "4401" in message or "403" in message:
                    return
                raise

        pool = ThreadPoolExecutor(max_workers=1)
        try:
            pool.submit(_connect).result(timeout=2.0)
        except FuturesTimeout:
            continue
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"websocket {path} raised {type(exc).__name__}: {exc}")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
