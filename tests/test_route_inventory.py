"""Smoke every mounted HTTP/WebSocket route (operator profile).

Unauthenticated operator APIs should 401 via middleware. Public handlers may
return 2xx/3xx/4xx. 5xx fails the inventory. Streaming endpoints are bounded
by a short timeout so SSE generators cannot hang CI.
"""

from __future__ import annotations

import os
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any

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

# Floor so dropping platform routers cannot silently shrink CI coverage.
MIN_HTTP_ROUTES = 90
MIN_API_ROUTES = 70
_SENTINEL_UUID = "00000000-0000-0000-0000-000000000001"
_STREAM_HINTS = ("/events", "/tts/stream", "/ws")
_SKIP_METHODS = frozenset({"HEAD", "OPTIONS"})


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
    client: TestClient,
    method: str,
    path: str,
    *,
    timeout: float,
    json_body: dict[str, Any] | None,
) -> Any:
    kwargs: dict[str, Any] = {}
    if json_body is not None:
        kwargs["json"] = json_body
    fn = getattr(client, method.lower())

    def _invoke() -> Any:
        try:
            return fn(path, follow_redirects=False, **kwargs)
        except TypeError:
            return fn(path, **kwargs)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_invoke)
        return future.result(timeout=timeout)


def _probe(
    client: TestClient,
    method: str,
    template: str,
) -> tuple[str, int | str]:
    path = _fill_path(template)
    json_body = None if method in {"GET", "DELETE"} else {}
    timeout = 1.5 if _is_streaming(template) else 8.0
    try:
        response = _call(client, method, path, timeout=timeout, json_body=json_body)
    except FuturesTimeout:
        if _is_streaming(template):
            return path, 200
        raise
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"{method} {path} raised {type(exc).__name__}: {exc}")
    return path, int(response.status_code)


def _require_postgres() -> None:
    if _postgres_listening():
        return
    if os.environ.get("CI"):
        pytest.fail("Postgres on 127.0.0.1:5432 is required for route inventory in CI")
    pytest.skip("Postgres not listening on 127.0.0.1:5432")


def _login_operator(client: TestClient) -> None:
    password = "password123"
    created = client.post(
        "/api/operators",
        json={"username": "admin", "display_name": "Admin", "password": password},
    )
    if created.status_code not in {200, 400, 401, 403, 409}:
        pytest.fail(f"create operator failed: {created.status_code} {created.text}")
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": password},
    )
    if login.status_code != 200:
        login = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
    assert login.status_code == 200, f"login failed: {login.status_code} {login.text}"


@pytest.fixture(scope="module")
def inventory_client() -> TestClient:
    _ensure_platform_routes()
    try:
        client = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
    except TypeError:
        client = TestClient(app, raise_server_exceptions=False)
    with client:
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
    assert len(http_rows) >= MIN_HTTP_ROUTES, (
        f"expected at least {MIN_HTTP_ROUTES} HTTP routes, found {len(http_rows)}"
    )
    assert len(api_rows) >= MIN_API_ROUTES, (
        f"expected at least {MIN_API_ROUTES} /api routes, found {len(api_rows)}"
    )


def test_all_http_routes_unauthenticated(inventory_client: TestClient) -> None:
    _require_postgres()
    failures: list[str] = []
    seen = 0
    for method, template in _iter_http_routes():
        path, status = _probe(inventory_client, method, template)
        seen += 1
        if isinstance(status, int) and status >= 500:
            failures.append(f"{method} {path} -> {status}")
    assert seen >= MIN_HTTP_ROUTES
    assert not failures, "5xx (or unexpected) responses:\n" + "\n".join(failures)


def test_all_http_routes_authenticated(inventory_client: TestClient) -> None:
    _require_postgres()
    _login_operator(inventory_client)
    failures: list[str] = []
    for method, template in _iter_http_routes():
        path, status = _probe(inventory_client, method, template)
        if isinstance(status, int) and status >= 500:
            failures.append(f"{method} {path} -> {status}")
    assert not failures, "authenticated 5xx responses:\n" + "\n".join(failures)


def test_websocket_routes_do_not_500(inventory_client: TestClient) -> None:
    _require_postgres()
    paths = _iter_ws_routes()
    if not paths:
        pytest.skip("no websocket routes mounted")
    for template in paths:
        path = _fill_path(template)
        try:
            with inventory_client.websocket_connect(path) as ws:
                ws.close()
        except WebSocketDisconnect:
            continue
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            if "1008" in message or "4401" in message or "403" in message:
                continue
            pytest.fail(f"websocket {path} raised {type(exc).__name__}: {exc}")
