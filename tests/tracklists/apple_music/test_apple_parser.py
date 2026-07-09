"""Apple Music DJ mix parser tests."""

from __future__ import annotations

import json
from pathlib import Path

from maya_feeds.apple_music import parse_apple_music_html

from tests.tracklists.conftest import assert_golden_entries

FIXTURES = Path(__file__).resolve().parent / "fixtures"
URL = "https://music.apple.com/us/album/alexandra-palace-london-feb-27-2026-dj-mix/1890298647"


def test_fred_again_apple_music_fixture():
    html = (FIXTURES / "fred_again_apple_music.html").read_text()
    parsed = parse_apple_music_html(URL, html)
    assert parsed is not None
    assert parsed.album_id == "1890298647"
    assert len(parsed.entries) == 3
    assert parsed.entries[0].track_id == "1890298648"
    assert parsed.entries[0].duration_seconds == 300
    assert parsed.entries[1].start_seconds == 300
    assert parsed.entries[1].end_seconds == 720
    assert parsed.attrs.get("mix_context") is True
    assert any("youtube.com/watch?v=gfF8jzBVWvM" in u for u in parsed.linked_urls)
    assert any("1001tracklists.com" in u for u in parsed.linked_urls)


def test_fred_again_apple_golden_fields():
    html = (FIXTURES / "fred_again_apple_music.html").read_text()
    golden = json.loads((FIXTURES / "fred_again_expected.json").read_text())
    parsed = parse_apple_music_html(URL, html)
    assert parsed is not None
    assert len(parsed.entries) == golden["track_count"]
    assert_golden_entries(parsed.entries, golden["entries"])
