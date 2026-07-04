"""Tests for VOICE: delivery cue stripping in text-chat streams."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.paths import setup_paths, VOICE_RUNTIME

setup_paths()
sys.path.insert(0, str(VOICE_RUNTIME))

from agent import strip_voice_cue_stream, _split_voice_cue, _strip_voice_delivery_line  # noqa: E402
from services.voice.hub import _voice_cue_filtered_stream  # noqa: E402


def _tokenize(text: str, size: int = 4) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def test_split_newline_form() -> None:
    raw = "VOICE: warm, thoughtful, slightly vulnerable\nYou know, Dad..."
    cue, reply = _split_voice_cue(raw, eof=True)
    assert cue == "warm, thoughtful, slightly vulnerable"
    assert reply == "You know, Dad..."


def test_split_inline_form() -> None:
    raw = "VOICE: soft, hopeful, a little shy Hey, Myles. I was just thinking..."
    cue, reply = _split_voice_cue(raw, eof=True)
    assert cue == "soft, hopeful, a little shy"
    assert reply.startswith("Hey, Myles")


def test_strip_delivery_line() -> None:
    raw = "VOICE: playful, teasing\nFive... four..."
    assert _strip_voice_delivery_line(raw) == "Five... four..."


def test_stream_stripper_chunked() -> None:
    raw = "VOICE: bright, cheerful, tilting head\nHi! You know..."
    reply = "".join(strip_voice_cue_stream(iter(_tokenize(raw))))
    assert "VOICE:" not in reply
    assert reply.startswith("Hi!")


def test_hub_filtered_stream() -> None:
    raw = "VOICE: sing-song, counting down\nTen... nine..."
    reply = "".join(_voice_cue_filtered_stream(iter(_tokenize(raw))))
    assert "VOICE:" not in reply
    assert reply.startswith("Ten")
