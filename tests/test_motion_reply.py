"""Motion turns must still produce spoken dialogue for TTS."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "packages" / "voice-runtime"
sys.path.insert(0, str(ROOT))

from agent import VoiceAgent, finalize_reply_text  # noqa: E402


def test_asterisk_only_reply_finalizes_empty():
    reply, _ = finalize_reply_text("*waves cheerfully at everyone*")
    assert reply == ""


def test_audience_fallback_after_empty_gesture_reply():
    agent = VoiceAgent(mode="ptt")
    text = "Say hello to everyone"
    raw = "*waves*"
    spoken, _ = finalize_reply_text(raw)
    assert spoken == ""
    fallback = agent._fallback_avatar_reply(text, "wave")
    assert fallback == "Hello everyone!"


def test_say_hi_to_everyone_fallback():
    agent = VoiceAgent(mode="ptt")
    fallback = agent._fallback_avatar_reply("Say hi to everyone", "wave")
    assert fallback == "Hi everyone!"
