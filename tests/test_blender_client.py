"""Tests for Blender MCP client helpers."""

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from services.artifacts.store import artifact_url_for_path, blender_outputs_root, save_image_bytes
from services.blender.client import BlenderToolResult, parse_tool_result


def test_parse_tool_result_text_only():
    result = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="hello scene")],
        isError=False,
    )
    parsed = parse_tool_result(result)
    assert parsed.text == "hello scene"
    assert parsed.images == []
    assert parsed.is_error is False


def test_parse_tool_result_image_base64():
    raw = b"\x89PNG\r\n\x1a\n"
    encoded = base64.b64encode(raw).decode("ascii")
    result = SimpleNamespace(
        content=[SimpleNamespace(type="image", data=encoded, text=None)],
        isError=False,
    )
    parsed = parse_tool_result(result)
    assert parsed.images == [raw]
    assert parsed.text == "ok"


def test_parse_tool_result_error():
    result = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="addon not connected")],
        isError=True,
    )
    parsed = parse_tool_result(result)
    assert parsed.is_error is True
    assert "addon" in parsed.text


def test_save_image_bytes_and_url():
    path = save_image_bytes(b"png-bytes", suffix=".png")
    assert path.is_file()
    url = artifact_url_for_path(path)
    assert url.startswith("/blender-outputs/")
    assert blender_outputs_root() in path.parents or path.parent == blender_outputs_root()


def test_resolve_blender_mcp_config_env_override(monkeypatch):
    monkeypatch.setenv("MAYA_BLENDER_MCP_COMMAND", "/env/blender-mcp")
    from services.blender.client import _resolve_blender_mcp_config

    command, args, _env = _resolve_blender_mcp_config()
    assert command == "/env/blender-mcp"
    assert args == []
