"""VC incomplete-utterance detection + web-search guard."""

from __future__ import annotations

from tools.discord_bot import _vc_transcript_looks_incomplete


def test_vc_incomplete_ellipsis_and_about() -> None:
    assert _vc_transcript_looks_incomplete("Can you tell me about...")
    assert _vc_transcript_looks_incomplete("Can you tell me about")
    assert _vc_transcript_looks_incomplete("tell me about the")
    assert not _vc_transcript_looks_incomplete(
        "Can you tell me about the last video posted in YouTubes?"
    )
    assert not _vc_transcript_looks_incomplete("What's the weather in Denver?")


def test_classify_web_skips_incomplete_tell_me_about() -> None:
    from agent import VoiceAgent

    class _Stub:
        discord = None

        def _classify_discord_command(self, _t):
            return None

        def _wants_discord_youtube_summary(self, _t):
            return False

    stub = _Stub()
    assert VoiceAgent._classify_web_command(stub, "Can you tell me about...") is None
    assert VoiceAgent._classify_web_command(stub, "Can you tell me about") is None
    assert (
        VoiceAgent._classify_web_command(stub, "Can you tell me about quantum computing")
        == "search"
    )
