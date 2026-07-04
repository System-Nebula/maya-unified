"""Tests for leaked plain-text tool call parsing (any model)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "packages" / "voice-runtime"
sys.path.insert(0, str(ROOT))

from agent import VoiceAgent, finalize_reply_text  # noqa: E402
from memory.character_card import extract_pseudo_tool_calls  # noqa: E402
from tools.text_calls import parse_text_tool_calls, strip_text_tool_calls  # noqa: E402


def test_parse_wrapped_call_syntax():
    raw = (
        '<|tool_call>call:discord_play_youtube{query:<|"|>creepynuts daten<|"|>}'
        "<|tool_call|>"
    )
    calls = parse_text_tool_calls(raw)
    assert calls == [("discord_play_youtube", {"query": "creepynuts daten"})]
    assert strip_text_tool_calls(raw) == ""
    reply, _ = finalize_reply_text(raw)
    assert reply == ""


def test_parse_json_tool_blob():
    raw = '{"tool": "discord_play_youtube", "args": {"query": "creepy nuts daten"}}'
    calls = parse_text_tool_calls(raw)
    assert calls == [("discord_play_youtube", {"query": "creepy nuts daten"})]


def test_parse_function_tag_syntax():
    raw = '<function=discord_queue_youtube>{"query": "next track"}</function>'
    calls = parse_text_tool_calls(raw)
    assert calls == [("discord_queue_youtube", {"query": "next track"})]


def test_parse_paren_call_syntax():
    raw = 'discord_play_youtube(query="DATEN")'
    calls = parse_text_tool_calls(raw)
    assert calls == [("discord_play_youtube", {"query": "DATEN"})]


def test_extract_play_query_with_tool_preamble():
    text = "holy shit use your tool and play creepy nuts daten"
    tl = text.lower()
    assert VoiceAgent._extract_play_query(tl, text) == "creepy nuts daten"


def test_spoken_leaked_tool_result():
    assert (
        VoiceAgent._spoken_leaked_tool_result(
            "discord_play_youtube",
            {"playing": "Creepy Nuts - DATEN"},
        )
        == "Playing Creepy Nuts - DATEN."
    )


def test_extract_pseudo_includes_inline_call():
    raw = 'call:discord_queue_youtube{query:"next song"}'
    calls = extract_pseudo_tool_calls(raw)
    assert ("discord_queue_youtube", {"query": "next song"}) in calls
