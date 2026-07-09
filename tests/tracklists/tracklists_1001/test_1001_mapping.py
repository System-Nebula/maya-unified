"""1001tracklists parsed document → TracklistResolved mapping."""

from __future__ import annotations
from pathlib import Path

from maya_feeds.tracklist.normalize import parsed_to_tracklist_resolved
from maya_feeds.tracklist.protocol import PLATFORM_1001TL
from maya_feeds.tracklists_1001 import parse_1001tracklists_html
from services.music.set_bridge import tracklist_to_resolved_set

from tests.tracklists.conftest import assert_set_contract

FIXTURES = Path(__file__).resolve().parent / "fixtures"
URL = "https://www.1001tracklists.com/tracklist/2gu8q2xk/fred-again-thomas-bangalter-usb002.html"


def test_fred_again_1001_to_resolved_set():
    html = (FIXTURES / "fred_again_1001tl.html").read_text()
    parsed = parse_1001tracklists_html(URL, html)
    assert parsed is not None
    tracklist = parsed_to_tracklist_resolved(parsed)
    assert_set_contract(tracklist)
    assert tracklist.set_key == f"{PLATFORM_1001TL}:2gu8q2xk"
    assert tracklist.container_schema == PLATFORM_1001TL
    for entry in tracklist.entries:
        assert entry.source_refs[0].schema_id == PLATFORM_1001TL
        assert entry.source_refs[0].external_id.startswith("2gu8q2xk:")

    resolved = tracklist_to_resolved_set(tracklist)
    assert_set_contract(resolved)
