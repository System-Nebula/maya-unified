"""Platform OAuth route tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from apps.gateway.platform_auth_routes import router as platform_auth_router  # noqa: E402
from fastapi import FastAPI  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(platform_auth_router)
    return TestClient(app)


def test_platform_auth_status_unconfigured(client: TestClient) -> None:
    with patch(
        "apps.gateway.platform_auth_routes.google_oauth_configured",
        return_value=False,
    ):
        res = client.get("/api/platform/auth/status")
    assert res.status_code == 200
    data = res.json()
    assert data["oauth_available"] is False
    assert data["providers"] == []


def test_platform_auth_status_configured(client: TestClient) -> None:
    with patch(
        "apps.gateway.platform_auth_routes.google_oauth_configured",
        return_value=True,
    ):
        res = client.get("/api/platform/auth/status")
    assert res.status_code == 200
    data = res.json()
    assert data["oauth_available"] is True
    assert "google" in data["providers"]
    google = data["google"]
    assert "console_checklist" in google
    assert "redirect_uris" in google["console_checklist"]
    assert "javascript_origins" in google["console_checklist"]


def test_platform_oauth_login_passes_redirect_uri(client: TestClient) -> None:
    captured: dict = {}

    async def _fake_create_pkce_state(session, **kwargs):
        captured.update(kwargs)
        return ("https://accounts.google.com/o/oauth2/auth?test=1", "state", "verifier")

    with (
        patch(
            "apps.gateway.platform_auth_routes.google_oauth_configured",
            return_value=True,
        ),
        patch(
            "apps.gateway.platform_auth_routes.redirect_uri_for_request",
            return_value="http://testserver/auth/google/callback",
        ),
        patch(
            "apps.gateway.platform_auth_routes.create_pkce_state",
            side_effect=_fake_create_pkce_state,
        ),
    ):
        res = client.get("/api/platform/auth/login/google", follow_redirects=False)
    assert res.status_code == 307
    assert captured.get("redirect_uri") == "http://testserver/auth/google/callback"


def test_platform_oauth_login_unconfigured(client: TestClient) -> None:
    with patch(
        "apps.gateway.platform_auth_routes.google_oauth_configured",
        return_value=False,
    ):
        res = client.get("/api/platform/auth/login/google")
    assert res.status_code == 503


def test_platform_oauth_login_redirect(client: TestClient) -> None:
    with (
        patch(
            "apps.gateway.platform_auth_routes.google_oauth_configured",
            return_value=True,
        ),
        patch(
            "apps.gateway.platform_auth_routes.create_pkce_state",
            return_value=("https://accounts.google.com/o/oauth2/auth?test=1", "state", "verifier"),
        ),
    ):
        res = client.get("/api/platform/auth/login/google", follow_redirects=False)
    assert res.status_code == 307
    assert "accounts.google.com" in res.headers["location"]


def test_platform_oauth_unknown_provider(client: TestClient) -> None:
    res = client.get("/api/platform/auth/login/unknown")
    assert res.status_code == 404
