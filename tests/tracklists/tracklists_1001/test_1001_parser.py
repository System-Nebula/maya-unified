"""1001tracklists parser tests."""

from __future__ import annotations

import json
from pathlib import Path

from maya_feeds.tracklists_1001 import parse_1001tracklists_html

from tests.tracklists.conftest import assert_golden_entries

FIXTURES = Path(__file__).resolve().parent / "fixtures"
URL = "https://www.1001tracklists.com/tracklist/2gu8q2xk/fred-again-thomas-bangalter-usb002.html"


def test_fred_again_1001tracklists_fixture():
    html = (FIXTURES / "fred_again_1001tl.html").read_text()
    parsed = parse_1001tracklists_html(URL, html)
    assert parsed is not None
    assert parsed.tracklist_id == "2gu8q2xk"
    assert len(parsed.entries) == 3
    assert parsed.entries[0].artist == "Fred again.. & Swedish House Mafia"
    assert parsed.entries[1].start_seconds == 5 * 60 + 12
    assert any("youtube.com/watch?v=gfF8jzBVWvM" in u for u in parsed.linked_urls)
    assert any("music.apple.com" in u for u in parsed.linked_urls)


def test_fred_again_1001_golden_fields():
    html = (FIXTURES / "fred_again_1001tl.html").read_text()
    golden = json.loads((FIXTURES / "fred_again_expected.json").read_text())
    parsed = parse_1001tracklists_html(URL, html)
    assert parsed is not None
    assert len(parsed.entries) == golden["track_count"]
    assert_golden_entries(parsed.entries, golden["entries"])
