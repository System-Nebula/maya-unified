"""Tests for chat cmd routing through agent_chat."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_agent_chat_source_routes_cmds_before_hub():
    src = (ROOT / "apps" / "gateway" / "voice_routes.py").read_text(encoding="utf-8")
    chat_block = src.split("async def agent_chat", 1)[1].split("def agent_speak", 1)[0]
    assert "try_dispatch_chat_cmd_async" in chat_block
    assert chat_block.index("try_dispatch_chat_cmd_async") < chat_block.index("hub.chat_text")


@pytest.fixture
def chat_client():
    sys.modules.setdefault("server", MagicMock(Hub=object))
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from apps.gateway.voice_routes import register_agent_routes

    app = FastAPI()
    register_agent_routes(app)
    return TestClient(app)


def test_agent_chat_dispatches_registered_cmd(chat_client) -> None:
    with patch("services.cmd.chat_bridge.try_dispatch_chat_cmd_async", new_callable=AsyncMock) as mock_dispatch:
        mock_dispatch.return_value = {"ok": True, "text": "Available cmds", "mode": "cmd"}
        res = chat_client.post("/api/voice/agent/chat", json={"text": "/help"})
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert res.json()["mode"] == "cmd"
    mock_dispatch.assert_called_once_with("/help", operator_id=None)


def test_agent_chat_falls_through_for_plain_text(chat_client) -> None:
    with patch("services.cmd.chat_bridge.try_dispatch_chat_cmd_async", new_callable=AsyncMock) as mock_dispatch:
        mock_dispatch.return_value = None
        with patch("apps.gateway.voice_routes.hub") as mock_hub:
            mock_hub.chat_text.return_value = {"ok": True, "text": "hello back", "mode": "basic"}
            res = chat_client.post("/api/voice/agent/chat", json={"text": "hello there"})
    assert res.status_code == 200
    assert res.json()["text"] == "hello back"
    mock_hub.chat_text.assert_called_once_with("hello there", operator_id=None)


def test_agent_chat_falls_through_for_unknown_slash(chat_client) -> None:
    with patch("services.cmd.chat_bridge.try_dispatch_chat_cmd_async", new_callable=AsyncMock) as mock_dispatch:
        mock_dispatch.return_value = None
        with patch("apps.gateway.voice_routes.hub") as mock_hub:
            mock_hub.chat_text.return_value = {"ok": True, "text": "thinking", "mode": "enriched"}
            chat_client.post("/api/voice/agent/chat", json={"text": "/unknown-command"})
    mock_hub.chat_text.assert_called_once_with("/unknown-command", operator_id=None)
