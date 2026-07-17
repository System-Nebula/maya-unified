"""Smart transcript chunker + YouTube smart_summary wiring."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tools.transcript_chunker import TranscriptChunker, TranscriptSummarizer
from tools.youtube_transcript import youtube_transcript


def test_chunker_splits_long_estimated_transcript() -> None:
    # ~40 minutes of speech at 150 wpm → multiple 10-min chunks
    words = ["word"] * (150 * 40)
    text = " ".join(words)
    chunks = TranscriptChunker(chunk_duration_minutes=10, overlap_minutes=1).chunk_transcript(
        text
    )
    assert len(chunks) >= 3
    assert chunks[0].total_chunks == len(chunks)
    assert all(c.text for c in chunks)


def test_chunker_uses_segment_timestamps() -> None:
    segments = [
        {
            "text": f"segment number {i} with enough characters to pass the minimum filter. ",
            "start": float(i * 60),
            "duration": 50.0,
        }
        for i in range(25)  # 25 minutes
    ]
    chunks = TranscriptChunker(chunk_duration_minutes=10, overlap_minutes=1).chunk_transcript(
        "",
        transcript_segments=segments,
    )
    assert len(chunks) >= 2
    assert "segment number 0" in chunks[0].text


def test_summarizer_multi_pass_calls_complete() -> None:
    calls: list[int] = []

    def complete(messages, max_tokens):
        calls.append(max_tokens)
        user = messages[-1]["content"]
        if "Section 1:" in user:
            return "Final merged summary of the whole video."
        return f"Chunk summary for tokens={max_tokens}"

    # Force multiple chunks via segments spanning ~25 minutes
    segments = [
        {"text": ("topic " * 40).strip(), "start": float(i * 60), "duration": 55.0}
        for i in range(25)
    ]
    text = " ".join(s["text"] for s in segments)
    result = TranscriptSummarizer(complete, max_summary_tokens=400).summarize_transcript(
        text,
        transcript_segments=segments,
        video_title="Demo",
    )
    assert result["ok"] is True
    assert result["method"] == "multi_pass"
    assert result["num_chunks"] >= 2
    assert "Final merged" in result["summary"]
    assert len(calls) >= 3  # per-chunk + merge


def test_youtube_transcript_attaches_smart_summary() -> None:
    # Long enough to trigger smart path (>= 5000 chars)
    long_text = ("interesting point about space travel. " * 200).strip()
    assert len(long_text) >= 5000
    snippets = [
        SimpleNamespace(text=long_text[i : i + 200], start=float(i), duration=1.0)
        for i in range(0, min(len(long_text), 8000), 200)
    ]
    # Ensure join reconstructs enough length
    joined = " ".join(s.text for s in snippets)
    if len(joined) < 5000:
        snippets = [SimpleNamespace(text=long_text, start=0.0, duration=600.0)]

    transcript = MagicMock()
    transcript.fetch.return_value = snippets
    transcript.language_code = "en"
    transcript_list = MagicMock()
    transcript_list.find_transcript.return_value = transcript
    transcript_list.__iter__ = lambda self: iter([transcript])
    api = MagicMock()
    api.list.return_value = transcript_list

    def fake_complete(messages, max_tokens):
        return "Smart factual summary of the long video."

    with patch("youtube_transcript_api.YouTubeTranscriptApi", return_value=api):
        result = youtube_transcript(
            "dQw4w9WgXcQ",
            max_chars=800,
            smart_summarize=True,
            llm_complete=fake_complete,
        )

    assert result["ok"] is True
    assert result.get("smart_summary")
    assert "Smart factual" in result["smart_summary"]
    assert result.get("smart_summary_chunks", 0) >= 1


def test_summarize_prefers_smart_summary() -> None:
    from agent import VoiceAgent

    agent = VoiceAgent.__new__(VoiceAgent)
    agent.llm = MagicMock()
    agent.llm.base_system_prompt.return_value = "You are Maya."
    agent.llm.complete.return_value = MagicMock(
        content="Spoken rewrite of the smart summary."
    )

    out = VoiceAgent._summarize_youtube_transcript(
        agent,
        "summarize this",
        {
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "transcript": "raw truncated junk",
            "smart_summary": "Full factual pre-summary covering chapters one through five.",
            "truncated": True,
        },
    )
    assert "Spoken rewrite" in out
    user_msg = agent.llm.complete.call_args[0][0][-1]["content"]
    assert "Pre-summarized" in user_msg or "pre-summary" in user_msg.lower()
    assert "Full factual pre-summary" in user_msg
    assert "raw truncated junk" not in user_msg
