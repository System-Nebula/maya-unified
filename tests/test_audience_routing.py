"""Audience greetings must not route to Discord channel posts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "packages" / "voice-runtime"
sys.path.insert(0, str(ROOT))

from agent import VoiceAgent  # noqa: E402


def test_say_hello_to_everyone_is_not_discord_channel():
    text = "Say hello to everyone"
    tl = text.lower()
    assert VoiceAgent._is_local_audience_request(tl, text)
    assert VoiceAgent._extract_channel_message(tl, text) is None


def test_post_in_general_still_discord():
    text = "Post hello in general"
    tl = text.lower()
    assert not VoiceAgent._is_local_audience_request(tl, text)
    extracted = VoiceAgent._extract_channel_message(tl, text)
    assert extracted == ("hello", "general")
