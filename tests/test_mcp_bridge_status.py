"""Tests for MCP bridge diagnostic status."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
_VR = _ROOT / "packages" / "voice-runtime"
if str(_VR) not in sys.path:
    sys.path.insert(0, str(_VR))

from tools.mcp_bridge import MCPManager, resolve_mcp_config_path  # noqa: E402


def test_resolve_mcp_config_path_relative():
    path = resolve_mcp_config_path("mcp_servers.json.example")
    assert path.endswith("mcp_servers.json.example")
    assert Path(path).is_file()


def test_status_config_missing(tmp_path):
    missing = tmp_path / "missing.json"
    mgr = MCPManager(str(missing))
    mgr.start()
    status = mgr.status()
    assert status["hint"] is not None
    assert "not found" in status["hint"].lower()
    assert status["servers"] == {}


def test_status_no_enabled_servers(tmp_path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"servers": {"off": {"enabled": False}}}), encoding="utf-8")
    mgr = MCPManager(str(cfg))
    mgr.start()
    status = mgr.status()
    assert status["hint"] is not None
    assert "no mcp servers enabled" in status["hint"].lower()
    assert status["servers"] == {}


def test_status_package_missing_lists_servers(tmp_path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text(
        json.dumps(
            {
                "servers": {
                    "blender": {
                        "command": "/bin/false",
                        "enabled": True,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    mgr = MCPManager(str(cfg))
    with patch("tools.mcp_bridge._mcp_package_installed", return_value=False):
        mgr.start()
    status = mgr.status()
    assert status["package_installed"] is False
    assert "blender" in status["servers"]
    assert status["servers"]["blender"]["connected"] is False
    assert "uv sync --extra mcp" in status["servers"]["blender"]["error"]
    assert status["hint"] is not None
    assert "uv sync --extra mcp" in status["hint"]


def test_status_connected_server_hint_none(tmp_path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"servers": {}}), encoding="utf-8")
    mgr = MCPManager(str(cfg))
    mgr._server_status = {"blender": {"connected": True, "tools": 26}}
    status = mgr.status()
    assert status["connected_count"] == 1
    assert status["hint"] is None
