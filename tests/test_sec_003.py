"""SEC-003: command capability enforcement."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.gateway.cmd_routes import router as cmd_router
from apps.gateway.main import app as gateway_app
from services.auth.deps import require_operator
from services.cmd.bootstrap import ensure_cmds_registered
from services.cmd.dispatcher import dispatch_cmd_async
from services.cmd.models import CmdContext, CmdSurface, ParsedCmd
from services.cmd.registry import registry


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch):
    from services.cmd import bootstrap

    monkeypatch.setattr(bootstrap, "_bootstrapped", False)
    registry._by_id.clear()
    registry._alias_index.clear()
    ensure_cmds_registered()


@pytest.fixture
def operator_client(monkeypatch) -> TestClient:
    op = SimpleNamespace(id=uuid.uuid4(), role="operator", is_banned=False)

    async def fake_require_operator():
        return op

    app = FastAPI()
    app.include_router(cmd_router)
    app.dependency_overrides[require_operator] = fake_require_operator
    client = TestClient(app)
    client._test_operator = op  # type: ignore[attr-defined]
    return client


@pytest.mark.asyncio
async def test_ordinary_operator_cannot_execute_blender_code() -> None:
    ctx = CmdContext(
        operator_id="op-1",
        surface=CmdSurface.DASHBOARD,
        raw_text="/blend code import bpy; result = 1",
        metadata={"operator_role": "operator"},
    )
    result = await dispatch_cmd_async(
        ParsedCmd(cmd_id="blend", name="blend", args={"action": "code", "code": "result=1"}),
        ctx,
    )
    assert result.ok is False
    assert "blender.execute_code" in (result.error or "")


@pytest.mark.asyncio
async def test_admin_still_needs_env_flag_for_blender_code(monkeypatch) -> None:
    monkeypatch.delenv("MAYA_BLENDER_EXECUTE_CODE", raising=False)
    ctx = CmdContext(
        operator_id="admin-1",
        surface=CmdSurface.DASHBOARD,
        raw_text="/blend code import bpy; result = 1",
        metadata={"operator_role": "admin"},
    )
    result = await dispatch_cmd_async(
        ParsedCmd(cmd_id="blend", name="blend", args={"action": "code", "code": "result=1"}),
        ctx,
    )
    assert result.ok is False
    assert "MAYA_BLENDER_EXECUTE_CODE" in (result.error or "")


@pytest.mark.asyncio
async def test_admin_with_env_passes_capability_gate(monkeypatch) -> None:
    monkeypatch.setenv("MAYA_BLENDER_EXECUTE_CODE", "1")

    async def fake_run_code(*, code: str, blend_file=None):
        from services.blender.client import BlenderToolResult

        return BlenderToolResult(text="ok", is_error=False), []

    monkeypatch.setattr(
        "services.cmd.executors.blender.blender_run_code",
        fake_run_code,
    )
    ctx = CmdContext(
        operator_id="admin-1",
        surface=CmdSurface.DASHBOARD,
        raw_text="/blend code import bpy; result = 1",
        metadata={"operator_role": "admin", "corr_id": "c1"},
    )
    result = await dispatch_cmd_async(
        ParsedCmd(cmd_id="blend", name="blend", args={"action": "code", "code": "result=1"}),
        ctx,
    )
    assert result.ok is True


def test_dispatch_ignores_payload_operator_id(operator_client: TestClient) -> None:
    op = operator_client._test_operator  # type: ignore[attr-defined]
    foreign = str(uuid.uuid4())
    res = operator_client.post(
        "/api/cmds/dispatch",
        json={
            "text": "/help",
            "surface": "dashboard",
            "operator_id": foreign,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    # Route must not echo/use the foreign id; identity is principal-only.
    assert foreign not in str(body)


def test_anonymous_dispatch_returns_401() -> None:
    client = TestClient(gateway_app)
    assert client.post("/api/cmds/dispatch", json={"text": "/help"}).status_code == 401
