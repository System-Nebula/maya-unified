"""Platform OAuth stub route tests."""

from __future__ import annotations

import sys
from pathlib import Path

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


def test_platform_auth_status(client: TestClient) -> None:
    res = client.get("/api/platform/auth/status")
    assert res.status_code == 200
    data = res.json()
    assert data["oauth_available"] is False
    assert data["providers"] == []


def test_platform_oauth_login_stub(client: TestClient) -> None:
    res = client.get("/api/platform/auth/login/google")
    assert res.status_code == 501


def test_platform_oauth_unknown_provider(client: TestClient) -> None:
    res = client.get("/api/platform/auth/login/unknown")
    assert res.status_code == 404
