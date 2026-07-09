"""Tests for /game slash command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.cmd.bootstrap import ensure_cmds_registered
from services.cmd.dispatcher import dispatch_cmd_async
from services.cmd.models import CmdContext, CmdSurface
from services.cmd.parser import parse_cmd_input
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
async def test_parse_game_cmd():
    parsed = parse_cmd_input("/game reach the end of the game")
    assert parsed is not None
    assert parsed.cmd_id == "game"
    assert parsed.args["goal"] == "reach the end of the game"


@pytest.mark.asyncio
async def test_game_cmd_starts_play():
    mock_agent = MagicMock()
    mock_agent._run_game_play_until_goal.return_value = (
        "On it — playing Pokemon until: beat the game."
    )
    mock_hub = MagicMock(ready=True, agent=mock_agent, _active_operator_id="op-1")

    ctx = CmdContext(
        operator_id="op-1",
        surface=CmdSurface.CHAT,
        raw_text="/game beat the game",
    )
    parsed = parse_cmd_input("/game beat the game")
    assert parsed is not None

    with patch("services.cmd.executors.game._voice_hub", return_value=mock_hub):
        result = await dispatch_cmd_async(parsed, ctx)

    assert result.ok
    assert "playing" in (result.text or "").lower()
    mock_agent._run_game_play_until_goal.assert_called_once_with(
        "beat the game",
        profile_id="pokemon_gba",
    )


def test_game_in_discovery():
    ids = {item["id"] for item in registry.discovery(surface=CmdSurface.DASHBOARD)}
    assert "game" in ids
