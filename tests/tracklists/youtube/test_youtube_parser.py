"""YouTube tracklist parser tests."""

from __future__ import annotations

import json
from pathlib import Path

from maya_feeds.youtube_setlist import (
    parse_tracklist_lines,
    parse_youtube_set_from_info,
    split_artist_title,
)

from tests.tracklists.conftest import assert_golden_entries, assert_set_contract

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_split_artist_title_dash_and_x():
    assert split_artist_title("ATB - 9pm (Panteros666 EDIT)") == ("ATB", "9pm (Panteros666 EDIT)")
    assert split_artist_title("Look At Me - Vandal x edit")[0] == "Look At Me"


def test_andrea_botez_tracklist_count_and_timestamps():
    description = (FIXTURES / "andrea_botez_description.txt").read_text()
    entries = parse_tracklist_lines(description, duration_seconds=3600)
    assert len(entries) == 26
    brisa = next(e for e in entries if e.start_seconds == 4 * 60 + 34)
    assert "Brisa Bailo Sola" in brisa.label
    assert brisa.end_seconds == 6 * 60 + 42
    assert entries[0].label == "Hard Bounce"
    assert entries[-1].start_seconds == 55 * 60 + 30


def test_parse_youtube_set_from_info_andrea():
    description = (FIXTURES / "andrea_botez_description.txt").read_text()
    info = {
        "id": "u1NHX9FcHVw",
        "title": "HIGH ENERGY TECHNO MIX | Andrea Botez",
        "description": description,
        "duration": 3330,
        "webpage_url": "https://www.youtube.com/watch?v=u1NHX9FcHVw",
    }
    parsed = parse_youtube_set_from_info(info)
    assert parsed is not None
    assert parsed.video_id == "u1NHX9FcHVw"
    assert len(parsed.entries) == 26
    assert parsed.entries[3].title == "Brisa Bailo Sola - Mha iri Remix" or "Brisa Bailo Sola" in parsed.entries[3].label


def test_parse_youtube_set_from_info_fred_again_golden():
    info = json.loads((FIXTURES / "fred_again_ytdlp_info.json").read_text())
    golden = json.loads((FIXTURES / "fred_again_merged_expected.json").read_text())
    parsed = parse_youtube_set_from_info(info)
    assert parsed is not None
    assert parsed.video_id == golden["video_id"]
    assert len(parsed.entries) == golden["track_count"]
    assert_golden_entries(parsed.entries, golden["entries"])
