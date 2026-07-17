"""Regression: vision/screen phrases must not become Discord channel posts."""

from __future__ import annotations

from agent import VoiceAgent


def test_screen_again_and_tell_not_discord_channel() -> None:
    text = (
        "That's fine. Could you check the screen again and tell me "
        "what you think about this one?"
    )
    assert VoiceAgent._extract_channel_message(text.lower(), text) is None
    assert VoiceAgent._looks_like_vision_screen_request(text) is True


def test_real_channel_post_still_parses() -> None:
    text = "post hello everyone in #gaming"
    got = VoiceAgent._extract_channel_message(text.lower(), text)
    assert got is not None
    content, channel = got
    assert "hello" in content.lower()
    assert channel.lower().lstrip("#") == "gaming"


def test_stopword_channel_rejected() -> None:
    assert VoiceAgent._is_plausible_discord_channel("and") is False
    assert VoiceAgent._is_plausible_discord_channel("the") is False
    assert VoiceAgent._is_plausible_discord_channel("youtubes") is True


def test_confirm_pending_ignored_for_barge_fragment() -> None:
    from agent import _is_confirmation_like

    assert _is_confirmation_like("things say.") is False
    assert _is_confirmation_like("go ahead") is True
