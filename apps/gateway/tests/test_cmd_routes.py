"""Gateway cmd route tests."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from apps.gateway.cmd_routes import router as cmd_router  # noqa: E402
from services.auth.deps import require_operator  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch):
    from services.cmd import bootstrap

    monkeypatch.setattr(bootstrap, "_bootstrapped", False)
    from services.cmd.registry import registry

    registry._by_id.clear()
    registry._alias_index.clear()


@pytest.fixture
def client() -> TestClient:
    op = SimpleNamespace(id=uuid.uuid4(), role="operator", is_banned=False)

    async def fake_require_operator():
        return op

    app = FastAPI()
    app.include_router(cmd_router)
    app.dependency_overrides[require_operator] = fake_require_operator
    return TestClient(app)


def test_list_cmds_discovery(client: TestClient) -> None:
    res = client.get("/api/cmds?surface=dashboard")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert isinstance(body["cmds"], list)
    assert any(item["id"] == "help" for item in body["cmds"])
    assert any(item["id"] == "blend" for item in body["cmds"])
    assert all("executor" not in item for item in body["cmds"])


def test_dispatch_help(client: TestClient) -> None:
    res = client.post(
        "/api/cmds/dispatch",
        json={"text": "/help", "surface": "dashboard"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert "Available cmds" in body["text"]
