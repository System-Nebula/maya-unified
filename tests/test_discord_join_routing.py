"""Discord voice join must route through orchestrator/direct handlers, not roleplay."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]

from services.discord.channel_resolver import (  # noqa: E402
    execute_discord_join,
    extract_join_channel_hint,
    is_generic_channel_hint,
    wants_discord_join,
)


def test_wants_discord_join_detects_channel_requests():
    assert wants_discord_join("join hidden channel 4 myles")
    assert wants_discord_join("HELLO JOIN THE DISCORD CHANNEL PLEASE")
    assert not wants_discord_join("Hello?")


def test_extract_join_channel_hint():
    assert extract_join_channel_hint("join hidden channel 4 myles") == "hidden channel 4 myles"
    assert extract_join_channel_hint(
        "HELLO JOIN THE DISCORD CHANNEL PLEASE",
    ) == "DISCORD CHANNEL PLEASE"


def test_generic_channel_hint_uses_default():
    assert is_generic_channel_hint("DISCORD CHANNEL PLEASE")
    assert is_generic_channel_hint("discord channel")
    assert not is_generic_channel_hint("hidden channel 4 myles")


def test_resolve_join_channel_name_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(
        "services.discord.channel_resolver.load_settings",
        lambda: {"discord": {"default_voice_channel": "hidden channel 4 myles"}},
    )
    agent = MagicMock()
    agent.discord = MagicMock()
    agent.llm = MagicMock()
    from services.discord.channel_resolver import resolve_join_channel_name

    assert (
        resolve_join_channel_name(agent, "DISCORD CHANNEL PLEASE")
        == "hidden channel 4 myles"
    )


def test_execute_discord_join_uses_default_when_generic(monkeypatch):
    monkeypatch.setattr(
        "services.discord.channel_resolver.load_settings",
        lambda: {"discord": {"default_voice_channel": "hidden channel 4 myles"}},
    )
    agent = MagicMock()
    agent.discord = MagicMock()
    agent.discord.join_voice.return_value = {"joined": "hidden channel 4 myles"}

    def _fake_reply(_tool, _args, fn, ok=None, fail=None):
        result = fn()
        return ok(result) if callable(ok) else ok

    agent._discord_tool_reply.side_effect = _fake_reply

    reply = execute_discord_join(
        agent,
        "HELLO JOIN THE DISCORD CHANNEL PLEASE",
        "HELLO JOIN THE DISCORD CHANNEL PLEASE",
        channel_name="DISCORD CHANNEL PLEASE",
    )
    assert reply == "Joined hidden channel 4 myles."
    agent.discord.join_voice.assert_called_once_with("hidden channel 4 myles")


def test_hub_chat_text_executes_orchestrator_before_tool_loop():
    hub_src = (ROOT / "services" / "voice" / "hub.py").read_text(encoding="utf-8")
    chat_start = hub_src.index("def chat_text(")
    chat_end = hub_src.index("\n    def ", chat_start + 1)
    chat_block = hub_src[chat_start:chat_end]
    assert "_execute_orchestrator_plan" in chat_block
    assert chat_block.index("_execute_orchestrator_plan") < chat_block.index("tool_loop.run")
