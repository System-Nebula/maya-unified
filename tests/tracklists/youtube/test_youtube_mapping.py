"""YouTube parsed document → TracklistResolved / ResolvedSet mapping."""

from __future__ import annotations

import json
from pathlib import Path

from maya_feeds.tracklist.normalize import parsed_to_tracklist_resolved
from maya_feeds.tracklist.protocol import PLATFORM_YOUTUBE
from maya_feeds.youtube_setlist import parse_youtube_set_from_info
from services.music.set_bridge import tracklist_to_resolved_set

from tests.tracklists.conftest import assert_set_contract

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_andrea_ytdlp_to_resolved_set():
    info = json.loads((FIXTURES / "andrea_botez_ytdlp_info.json").read_text())
    parsed = parse_youtube_set_from_info(info)
    assert parsed is not None
    tracklist = parsed_to_tracklist_resolved(parsed)
    assert_set_contract(tracklist)
    assert tracklist.set_key == f"{PLATFORM_YOUTUBE}:u1NHX9FcHVw"
    assert len(tracklist.entries) == 26
    for entry in tracklist.entries:
        assert entry.source_refs[0].schema_id == PLATFORM_YOUTUBE
        assert entry.source_refs[0].external_id.startswith("u1NHX9FcHVw#")

    resolved = tracklist_to_resolved_set(tracklist)
    assert_set_contract(resolved)
    assert resolved.container_schema == PLATFORM_YOUTUBE


def test_fred_again_ytdlp_to_resolved_set():
    info = json.loads((FIXTURES / "fred_again_ytdlp_info.json").read_text())
    parsed = parse_youtube_set_from_info(info)
    assert parsed is not None
    tracklist = parsed_to_tracklist_resolved(parsed)
    assert_set_contract(tracklist)
    assert tracklist.set_key == f"{PLATFORM_YOUTUBE}:gfF8jzBVWvM"
    assert len(tracklist.entries) == 3
