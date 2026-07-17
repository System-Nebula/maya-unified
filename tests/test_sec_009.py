"""SEC-009: Discord shim authenticate-or-disable."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from discord_shim.main import (
    app,
    shim_enabled,
    validate_shim_config,
)


def test_shim_disabled_by_default() -> None:
    assert shim_enabled({}) is False
    with pytest.raises(RuntimeError, match="disabled"):
        validate_shim_config({})


def test_enabled_without_credentials_fails() -> None:
    with pytest.raises(RuntimeError, match="DISCORD_PUBLIC_KEY|DISCORD_SHIM_SERVICE_TOKEN"):
        validate_shim_config({"DISCORD_SHIM_ENABLED": "1"})


def test_unsigned_interaction_rejected(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_SHIM_ENABLED", "1")
    monkeypatch.setenv("DISCORD_SHIM_SERVICE_TOKEN", "shim-secret-token")
    client = TestClient(app)
    resp = client.post("/discord/interaction", json={"type": 1})
    assert resp.status_code == 401


def test_service_token_allows_ping(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_SHIM_ENABLED", "1")
    monkeypatch.setenv("DISCORD_SHIM_SERVICE_TOKEN", "shim-secret-token")
    client = TestClient(app)
    resp = client.post(
        "/discord/interaction",
        json={"type": 1},
        headers={"Authorization": "Bearer shim-secret-token"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"type": 1}


def test_disabled_runtime_returns_503(monkeypatch) -> None:
    monkeypatch.delenv("DISCORD_SHIM_ENABLED", raising=False)
    monkeypatch.delenv("DISCORD_SHIM_SERVICE_TOKEN", raising=False)
    client = TestClient(app)
    resp = client.post("/discord/interaction", json={"type": 1})
    assert resp.status_code == 503
