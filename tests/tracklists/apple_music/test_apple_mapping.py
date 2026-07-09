"""Apple Music parsed document → TracklistResolved mapping."""

from __future__ import annotations
from pathlib import Path

from maya_feeds.tracklist.normalize import parsed_to_tracklist_resolved
from maya_feeds.tracklist.protocol import PLATFORM_APPLE
from maya_feeds.apple_music import parse_apple_music_html
from services.music.set_bridge import tracklist_to_resolved_set

from tests.tracklists.conftest import assert_set_contract

FIXTURES = Path(__file__).resolve().parent / "fixtures"
URL = "https://music.apple.com/us/album/alexandra-palace-london-feb-27-2026-dj-mix/1890298647"


def test_fred_again_apple_to_resolved_set():
    html = (FIXTURES / "fred_again_apple_music.html").read_text()
    parsed = parse_apple_music_html(URL, html)
    assert parsed is not None
    tracklist = parsed_to_tracklist_resolved(parsed)
    assert_set_contract(tracklist)
    assert tracklist.set_key == f"{PLATFORM_APPLE}:1890298647"
    assert tracklist.container_schema == PLATFORM_APPLE
    for entry in tracklist.entries:
        assert entry.source_refs[0].schema_id == PLATFORM_APPLE

    resolved = tracklist_to_resolved_set(tracklist)
    assert_set_contract(resolved)
