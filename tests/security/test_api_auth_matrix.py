"""SEC-002: deny-by-default API auth matrix."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.gateway.main import app
from services.auth.api_auth_registry import (
    ApiAuthClass,
    classify_request,
    classify_route,
    explicit_entries,
    iter_mounted_api_routes,
    match_api_route,
    public_route_keys,
)


def test_every_mounted_api_route_is_classified() -> None:
    rows = iter_mounted_api_routes(app)
    assert rows, "expected mounted /api routes"
    for method, path in rows:
        auth_class = classify_route(method, path)
        assert isinstance(auth_class, ApiAuthClass)
        if auth_class is ApiAuthClass.PUBLIC:
            assert (method, path) in public_route_keys(), (
                f"{method} {path} classified public without registry entry"
            )


def test_public_entries_have_reasons() -> None:
    for entry in explicit_entries():
        assert entry.reason.strip(), f"missing reason for {entry.key}"


def test_cmds_fail_closed_without_session() -> None:
    client = TestClient(app)
    assert client.get("/api/cmds").status_code == 401
    assert client.post("/api/cmds/dispatch", json={"command": "noop"}).status_code == 401


def test_login_and_me_remain_public() -> None:
    client = TestClient(app)
    assert client.get("/api/auth/me").status_code != 401
    # login without body may 422, but must not be blocked as unauthenticated
    assert client.post("/api/auth/login", json={}).status_code != 401


def test_voice_status_still_requires_session() -> None:
    client = TestClient(app)
    assert client.get("/api/voice/agent/status").status_code == 401


def test_unmatched_api_path_is_not_open_handler() -> None:
    """Unknown /api paths must not match a classified open handler."""
    assert classify_request(app, "GET", "/api/definitely-not-a-route") is None
    client = TestClient(app)
    assert client.get("/api/definitely-not-a-route").status_code == 404


def test_room_guest_paths_match_templates() -> None:
    matched = match_api_route(app, "POST", "/api/rooms/demo/join")
    assert matched == ("POST", "/api/rooms/{slug}/join")
    assert classify_request(app, "POST", "/api/rooms/demo/join") is ApiAuthClass.ROOM_MEMBER


def test_new_route_cannot_be_public_by_omission() -> None:
    """Prefix omission must not invent public access — only explicit registry can."""
    assert classify_route("GET", "/api/brand-new-surface") is ApiAuthClass.OPERATOR
    assert ("GET", "/api/brand-new-surface") not in public_route_keys()


def test_voice_websocket_rejects_missing_and_invalid_session() -> None:
    from starlette.websockets import WebSocketDisconnect

    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as missing:
        with client.websocket_connect("/api/voice/agent/ws") as ws:
            ws.receive_text()
    assert missing.value.code == 4401

    client.cookies.set("maya_op_session", "not-a-valid-session")
    with pytest.raises(WebSocketDisconnect) as invalid:
        with client.websocket_connect("/api/voice/agent/ws") as ws:
            ws.receive_text()
    assert invalid.value.code == 4401
