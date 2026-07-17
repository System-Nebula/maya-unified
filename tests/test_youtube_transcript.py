"""YouTube transcript + Discord→YouTube chain helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tools.web import build_web_tools
from tools.youtube_transcript import (
    extract_video_id,
    extract_youtube_url,
    find_latest_youtube_url,
    youtube_transcript,
)


def test_extract_video_id_formats() -> None:
    vid = "dQw4w9WgXcQ"
    assert extract_video_id(vid) == vid
    assert extract_video_id(f"https://www.youtube.com/watch?v={vid}") == vid
    assert extract_video_id(f"https://youtu.be/{vid}") == vid
    assert extract_video_id(f"https://www.youtube.com/embed/{vid}") == vid
    assert extract_video_id(f"https://www.youtube.com/shorts/{vid}") == vid
    assert extract_video_id("not-a-video-id") is None
    assert extract_video_id("") is None


def test_extract_youtube_url_from_sentence() -> None:
    text = "Summarize https://youtu.be/dQw4w9WgXcQ for me please"
    assert extract_youtube_url(text) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_find_latest_youtube_url_newest_wins() -> None:
    messages = [
        {"content": "old https://youtu.be/AAAAAAAAAAA"},
        {"content": "noise"},
        {"content": "new https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
    ]
    assert find_latest_youtube_url(messages) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert find_latest_youtube_url([]) is None


def test_youtube_transcript_tool_registered() -> None:
    names = {t.name for t in build_web_tools()}
    assert "youtube_transcript" in names


def test_youtube_transcript_success_mocked() -> None:
    snippets = [
        SimpleNamespace(text="Hello world.", start=0.0, duration=1.0),
        SimpleNamespace(text="This is a demo.", start=1.0, duration=1.5),
    ]
    transcript = MagicMock()
    transcript.fetch.return_value = snippets
    transcript.language_code = "en"

    transcript_list = MagicMock()
    transcript_list.find_transcript.return_value = transcript
    transcript_list.__iter__ = lambda self: iter([transcript])

    api = MagicMock()
    api.list.return_value = transcript_list

    with patch("youtube_transcript_api.YouTubeTranscriptApi", return_value=api):
        result = youtube_transcript(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            smart_summarize=False,
        )

    assert result["ok"] is True
    assert result["video_id"] == "dQw4w9WgXcQ"
    assert "Hello world" in result["transcript"]
    assert result["num_segments"] == 2


def test_youtube_transcript_truncates() -> None:
    long_text = ("word " * 5000).strip()
    snippets = [SimpleNamespace(text=long_text, start=0.0, duration=10.0)]
    transcript = MagicMock()
    transcript.fetch.return_value = snippets
    transcript_list = MagicMock()
    transcript_list.find_transcript.return_value = transcript
    api = MagicMock()
    api.list.return_value = transcript_list

    with patch("youtube_transcript_api.YouTubeTranscriptApi", return_value=api):
        result = youtube_transcript("dQw4w9WgXcQ", max_chars=500, smart_summarize=False)

    assert result["ok"] is True
    assert result["truncated"] is True
    assert len(result["transcript"]) < len(long_text)
    assert "truncated" in result["transcript"].lower()


def test_classify_youtube_summarize_not_play() -> None:
    from agent import VoiceAgent

    class _Stub:
        discord = None
        _classify_discord_command = lambda self, t: None  # noqa: E731

    stub = _Stub()
    classify = VoiceAgent._classify_web_command
    assert (
        classify(
            stub,
            "Summarize https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )
        == "youtube_transcript"
    )
    assert (
        classify(
            stub,
            "Play https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        )
        != "youtube_transcript"
    )


def test_wants_discord_youtube_summary() -> None:
    from agent import VoiceAgent

    stub = VoiceAgent.__new__(VoiceAgent)
    stub.discord = object()
    stub._pending_channel_reply = None
    stub._pending_channel_post = None
    assert VoiceAgent._wants_discord_youtube_summary(
        stub, "Hey, can you tell me about the last video posted in YouTubes?"
    )
    assert VoiceAgent._wants_discord_youtube_summary(
        stub,
        "can you tell me about the last video posted in the discord channel youtubes?",
    )
    assert not VoiceAgent._wants_discord_youtube_summary(
        stub, "Summarize https://youtu.be/dQw4w9WgXcQ"
    )
    assert VoiceAgent._extract_discord_youtube_channel(
        stub, "last video posted in YouTubes"
    ).lower() in {"youtubes", "youtube"}
    assert (
        VoiceAgent._extract_discord_youtube_channel(
            stub,
            "last video posted in the discord channel youtubes?",
        ).lower()
        == "youtubes"
    )
    assert (
        VoiceAgent._classify_discord_command(
            stub,
            "can you tell me about the last video posted in the discord channel youtubes?",
        )
        == "channel_youtube_summary"
    )


def test_discord_youtube_summary_chain(monkeypatch) -> None:
    from agent import VoiceAgent

    events: list[str] = []

    class _Discord:
        def fetch_channel_messages(self, channel_name, limit=30, guild_name=None):
            assert "youtube" in channel_name.lower()
            return {
                "channel": channel_name,
                "messages": [
                    {"content": "old https://youtu.be/AAAAAAAAAAA"},
                    {"content": "check this https://youtu.be/dQw4w9WgXcQ"},
                ],
            }

    agent = VoiceAgent.__new__(VoiceAgent)
    agent.discord = _Discord()
    agent._emit = lambda **kw: events.append(str(kw.get("type") or ""))
    agent._bg_lock = __import__("threading").Lock()
    agent._bg_job_seq = 0
    agent._bg_jobs = {}
    agent._turn_corr_id = None
    agent.history = []
    announced: list[str] = []
    agent._announce_companion_result = lambda text, corr_id=None, label="": announced.append(text)

    monkeypatch.setattr(
        "tools.youtube_transcript.youtube_transcript",
        lambda url, max_chars=10000, **kw: {
            "ok": True,
            "url": url,
            "transcript": "A fun music video about never giving up.",
            "truncated": False,
        },
    )
    monkeypatch.setattr(
        agent,
        "_summarize_youtube_transcript",
        lambda user_text, result: "It's a classic about never giving up.",
    )

    out = agent._try_discord_youtube_summary(
        "tell me about the last video posted in YouTubes"
    )
    assert "checking" in out.lower() or "on it" in out.lower()
    # Background worker should finish quickly with mocks.
    for _ in range(50):
        if announced:
            break
        __import__("time").sleep(0.05)
    assert announced and "never giving up" in announced[0]
    assert "tool_start" in events
