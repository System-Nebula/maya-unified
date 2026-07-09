"""Async /game cmd dispatch regression tests."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from services.cmd.bootstrap import ensure_cmds_registered
from services.cmd.chat_bridge import try_dispatch_chat_cmd_async
from services.cmd.registry import registry


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch):
    from services.cmd import bootstrap

    monkeypatch.setattr("services.game.enabled.GAME_MODE_ENABLED", True)
    monkeypatch.setattr(bootstrap, "_bootstrapped", False)
    registry._by_id.clear()
    registry._alias_index.clear()
    ensure_cmds_registered()


@pytest.mark.asyncio
async def test_game_cmd_async_dispatch():
    mock_agent = MagicMock()
    mock_agent._run_game_play_until_goal.return_value = "On it — playing Pokemon."
    mock_hub = MagicMock(ready=True, agent=mock_agent, _active_operator_id="op-1")
    mock_hub.apply_operator_context = MagicMock()
    mock_hub.broadcast = MagicMock()

    mock_mod = type(sys)("services.voice.hub")
    mock_mod.hub = mock_hub

    with patch("services.cmd.executors.game._voice_hub", return_value=mock_hub), patch.dict(
        sys.modules, {"services.voice.hub": mock_mod}
    ), patch("services.cmd.chat_bridge._schedule_persist_cmd_turns"):
        out = await try_dispatch_chat_cmd_async(
            "/game beat the elite 4",
            operator_id="op-1",
        )

    assert out is not None
    assert out.get("ok") is True
    assert "playing" in (out.get("text") or "").lower()
