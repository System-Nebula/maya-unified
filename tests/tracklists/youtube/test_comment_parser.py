"""Tests for YouTube comment tracklist parsing."""

from __future__ import annotations

from pathlib import Path

from maya_feeds.youtube_setlist import parse_youtube_comment_tracklist

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_parse_youtube_comment_tracklist_footnotes_and_narrative():
    text = (FIXTURES / "fred_usb002_comment.txt").read_text()
    entries = parse_youtube_comment_tracklist(text, duration_seconds=6918)
    assert len(entries) >= 5
    first = entries[0]
    assert first.start_seconds == 1
    assert "Mythologies" in first.label
    assert first.attrs.get("footnote")
    narrative = next(e for e in entries if e.attrs.get("is_narrative"))
    assert "I remember" in narrative.label
    usher = next(e for e in entries if "Usher" in e.label)
    assert usher.attrs.get("footnote")
