"""Tests for /blend cmd executor."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from services.cmd.bootstrap import ensure_cmds_registered
from services.cmd.dispatcher import dispatch_cmd_async
from services.cmd.executors.blender import _parse_blend_args
from services.cmd.models import CmdContext, CmdSurface
from services.cmd.parser import parse_cmd_input
from services.cmd.registry import registry
from services.blender.client import BlenderToolResult


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch):
    from services.cmd import bootstrap

    monkeypatch.setattr(bootstrap, "_bootstrapped", False)
    registry._by_id.clear()
    registry._alias_index.clear()
    ensure_cmds_registered()


def test_blend_registered_on_dashboard():
    ids = {item["id"] for item in registry.discovery(surface=CmdSurface.DASHBOARD)}
    assert "blend" in ids


def test_parse_blend_screenshot():
    ctx = CmdContext(raw_text="/blend screenshot", surface=CmdSurface.DASHBOARD)
    parsed = _parse_blend_args(ctx, {})
    assert parsed["action"] == "screenshot"


def test_parse_blend_inspect_file():
    ctx = CmdContext(raw_text="/blend inspect /tmp/scene.blend", surface=CmdSurface.DASHBOARD)
    parsed = _parse_blend_args(ctx, {})
    assert parsed["action"] == "inspect"
    assert parsed["file"] == "/tmp/scene.blend"


def test_parse_blend_code():
    ctx = CmdContext(
        raw_text="/blend code import bpy; result = ['a']",
        surface=CmdSurface.DASHBOARD,
    )
    parsed = _parse_blend_args(ctx, {})
    assert parsed["action"] == "code"
    assert "import bpy" in parsed["code"]


def test_parse_blend_default_summary():
    ctx = CmdContext(raw_text="/blend", surface=CmdSurface.DASHBOARD)
    parsed = _parse_blend_args(ctx, {})
    assert parsed["action"] == "summary"


@pytest.mark.asyncio
async def test_dispatch_blend_summary():
    parsed = parse_cmd_input("/blend")
    assert parsed is not None
    assert parsed.cmd_id == "blend"
    mock_result = BlenderToolResult(text="Collection: Scene", is_error=False)
    with patch("services.cmd.executors.blender.blender_summary", AsyncMock(return_value=mock_result)):
        result = await dispatch_cmd_async(
            parsed,
            CmdContext(surface=CmdSurface.DASHBOARD, raw_text="/blend"),
        )
    assert result.ok is True
    assert "Blender scene summary" in result.text
    assert "Collection" in result.text


@pytest.mark.asyncio
async def test_dispatch_blend_screenshot_with_artifact():
    parsed = parse_cmd_input("/blend screenshot")
    assert parsed is not None
    tool_result = BlenderToolResult(text="ok", is_error=False)
    artifacts = [{"type": "image", "url": "/blender-outputs/2026-07-04/abc.png", "job_id": "abc"}]
    with patch(
        "services.cmd.executors.blender.blender_screenshot",
        AsyncMock(return_value=(tool_result, artifacts)),
    ):
        result = await dispatch_cmd_async(
            parsed,
            CmdContext(surface=CmdSurface.DASHBOARD, raw_text="/blend screenshot"),
        )
    assert result.ok is True
    assert result.artifacts == artifacts
    assert "/blender-outputs/" in result.text


@pytest.mark.asyncio
async def test_dispatch_blend_inspect_missing_file():
    parsed = parse_cmd_input("/blend inspect")
    assert parsed is not None
    result = await dispatch_cmd_async(
        parsed,
        CmdContext(surface=CmdSurface.DASHBOARD, raw_text="/blend inspect"),
    )
    assert result.ok is False
    assert "file" in (result.error or "")


@pytest.mark.asyncio
async def test_dispatch_blend_inspect():
    parsed = parse_cmd_input("/blend inspect /tmp/foo.blend")
    assert parsed is not None
    mock_result = BlenderToolResult(text='{"objects": 3}', is_error=False)
    mock_inspect = AsyncMock(return_value=mock_result)
    with patch("services.cmd.executors.blender.blender_inspect_file", mock_inspect):
        result = await dispatch_cmd_async(
            parsed,
            CmdContext(surface=CmdSurface.DASHBOARD, raw_text="/blend inspect /tmp/foo.blend"),
        )
    assert result.ok is True
    mock_inspect.assert_awaited_once_with("/tmp/foo.blend")
