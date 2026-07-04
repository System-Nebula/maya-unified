"""Tests for MCP bridge image content handling."""

from __future__ import annotations

import base64
import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
_VR = _ROOT / "packages" / "voice-runtime"
if str(_VR) not in sys.path:
    sys.path.insert(0, str(_VR))

from tools.mcp_bridge import MCPManager  # noqa: E402


def test_save_image_content_returns_url():
    raw = b"\x89PNG\r\n\x1a\n"
    encoded = base64.b64encode(raw).decode("ascii")
    item = SimpleNamespace(type="image", data=encoded, text=None)
    url = MCPManager._save_image_content(item)
    assert url is not None
    assert url.startswith("/blender-outputs/")


def test_save_image_content_ignores_text():
    item = SimpleNamespace(type="text", text="hello", data=None)
    assert MCPManager._save_image_content(item) is None
