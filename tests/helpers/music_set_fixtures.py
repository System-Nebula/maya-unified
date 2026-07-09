"""Shared fixtures for music ontology evaluation tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from maya_contracts import SourceRefModel
from maya_feeds.apple_music import parse_apple_music_html
from maya_feeds.tracklists_1001 import parse_1001tracklists_html
from maya_feeds.youtube_setlist import parse_youtube_set_from_info
from maya_feeds.tracklist.normalize import parsed_to_tracklist_resolved
from services.music.set_bridge import tracklist_to_resolved_set
from services.music.set_correlate import correlate_sets
from services.music.set_types import (
    PLATFORM_1001TL,
    PLATFORM_APPLE,
    PLATFORM_YOUTUBE,
    ResolvedSet,
    SetEntry,
)

TRACKLIST_ROOT = Path(__file__).resolve().parent.parent / "tracklists"
YT_FIXTURES = TRACKLIST_ROOT / "youtube" / "fixtures"
TL_FIXTURES = TRACKLIST_ROOT / "tracklists_1001" / "fixtures"
AM_FIXTURES = TRACKLIST_ROOT / "apple_music" / "fixtures"

# Back-compat alias
FIXTURES = YT_FIXTURES

ANDREA_URL = "https://www.youtube.com/watch?v=u1NHX9FcHVw&list=RDu1NHX9FcHVw"
ANDREA_URL_CANONICAL = "https://www.youtube.com/watch?v=u1NHX9FcHVw"

FRED_AGAIN_YT_URL = "https://www.youtube.com/watch?v=gfF8jzBVWvM"
FRED_AGAIN_1001TL_URL = (
    "https://www.1001tracklists.com/tracklist/2gu8q2xk/"
    "fred-again..-thomas-bangalter-usb002-alexandra-palace-london-united-kingdom-2026-02-27.html"
)
FRED_AGAIN_APPLE_URL = (
    "https://music.apple.com/us/album/alexandra-palace-london-feb-27-2026-dj-mix/1890298647"
)
FRED_AGAIN_SET_KEY = f"{PLATFORM_YOUTUBE}:gfF8jzBVWvM"


def load_andrea_description() -> str:
    return (YT_FIXTURES / "andrea_botez_description.txt").read_text()


def load_andrea_ytdlp_info() -> dict[str, Any]:
    return json.loads((YT_FIXTURES / "andrea_botez_ytdlp_info.json").read_text())


def load_andrea_expected() -> dict[str, Any]:
    return json.loads((YT_FIXTURES / "andrea_botez_expected.json").read_text())


def _entry_from_dict(row: dict[str, Any], *, video_id: str) -> SetEntry:
    position = int(row["position"])
    return SetEntry(
        position=position,
        start_seconds=int(row["start_seconds"]),
        end_seconds=row.get("end_seconds"),
        label=str(row["label"]),
        artist=row.get("artist"),
        title=row.get("title"),
        source_refs=[
            SourceRefModel(
                schema_id=PLATFORM_YOUTUBE,
                external_id=f"{video_id}#{position}",
                url=None,
                confidence=1.0,
            )
        ],
    )


def andrea_resolved_set(*, video_id: str | None = None) -> ResolvedSet:
    """Build a ``ResolvedSet`` from the Andrea Botez golden fixture."""
    golden = load_andrea_expected()
    vid = video_id or str(golden["video_id"])
    set_key = f"{PLATFORM_YOUTUBE}:{vid}"
    container_url = f"https://www.youtube.com/watch?v={vid}"
    entries = [_entry_from_dict(row, video_id=vid) for row in golden["entries"]]
    return ResolvedSet(
        set_key=set_key,
        title=str(golden["title"]),
        container_url=container_url,
        container_schema=PLATFORM_YOUTUBE,
        entries=entries,
        attrs={"duration_seconds": golden.get("duration_seconds")},
    )


def assert_golden_entries(actual: list[Any], expected_rows: list[dict[str, Any]]) -> None:
    """Diff-friendly assertion for parsed tracklist entries vs golden JSON rows."""
    assert len(actual) == len(expected_rows), (
        f"expected {len(expected_rows)} entries, got {len(actual)}"
    )
    for i, (entry, row) in enumerate(zip(actual, expected_rows, strict=True)):
        assert entry.position == row["position"], f"entry {i + 1} position"
        assert entry.start_seconds == row["start_seconds"], f"entry {i + 1} start_seconds"
        assert entry.end_seconds == row["end_seconds"], f"entry {i + 1} end_seconds"
        assert entry.label == row["label"], f"entry {i + 1} label"
        assert entry.artist == row.get("artist"), f"entry {i + 1} artist"
        assert entry.title == row.get("title"), f"entry {i + 1} title"


def reaction_entity_key(set_key: str, position: int) -> str:
    """Dashboard player reaction entity key for a virtual set track."""
    return f"{set_key}:{position}"


def load_fred_again_expected() -> dict[str, Any]:
    return json.loads((TL_FIXTURES / "fred_again_expected.json").read_text())


def load_fred_again_ytdlp_info() -> dict[str, Any]:
    return json.loads((YT_FIXTURES / "fred_again_ytdlp_info.json").read_text())


def fred_again_youtube_resolved() -> ResolvedSet:
    info = load_fred_again_ytdlp_info()
    parsed = parse_youtube_set_from_info(info)
    assert parsed is not None
    return tracklist_to_resolved_set(parsed_to_tracklist_resolved(parsed))


def fred_again_1001tl_resolved() -> ResolvedSet:
    html = (TL_FIXTURES / "fred_again_1001tl.html").read_text()
    parsed = parse_1001tracklists_html(FRED_AGAIN_1001TL_URL, html)
    assert parsed is not None
    return tracklist_to_resolved_set(parsed_to_tracklist_resolved(parsed))


def fred_again_apple_resolved() -> ResolvedSet:
    html = (AM_FIXTURES / "fred_again_apple_music.html").read_text()
    parsed = parse_apple_music_html(FRED_AGAIN_APPLE_URL, html)
    assert parsed is not None
    return tracklist_to_resolved_set(parsed_to_tracklist_resolved(parsed))


def fred_again_merged_resolved_set() -> ResolvedSet:
    """Fully correlated Fred Again set (YT container, 3 platforms per entry)."""
    yt = fred_again_youtube_resolved()
    tl = fred_again_1001tl_resolved()
    apple = fred_again_apple_resolved()
    return correlate_sets(correlate_sets(yt, tl), apple)


def mock_fetch_map() -> dict[str, ResolvedSet]:
    """URL -> ``ResolvedSet`` for offline ``fetch_and_parse_url`` mocking."""
    yt = fred_again_youtube_resolved()
    tl = fred_again_1001tl_resolved()
    apple = fred_again_apple_resolved()
    return {
        FRED_AGAIN_YT_URL: yt,
        FRED_AGAIN_1001TL_URL: tl,
        FRED_AGAIN_APPLE_URL: apple,
        "https://www.youtube.com/watch?v=gfF8jzBVWvM": yt,
        "https://www.1001tracklists.com/tracklist/2gu8q2xk/fred-again-thomas-bangalter-usb002.html": tl,
    }


def seed_fred_again_fetch_cache() -> None:
    """Pre-populate url cache so ``index_music_url`` runs offline."""
    from services.music.url_cache import cache_set

    tl_html = (TL_FIXTURES / "fred_again_1001tl.html").read_text()
    tl_short = "https://www.1001tracklists.com/tracklist/2gu8q2xk/fred-again-thomas-bangalter-usb002.html"

    cache_set("ytdlp", FRED_AGAIN_YT_URL, load_fred_again_ytdlp_info())
    cache_set("html", FRED_AGAIN_1001TL_URL, tl_html)
    cache_set("html", tl_short, tl_html)
    cache_set("html", FRED_AGAIN_APPLE_URL, (AM_FIXTURES / "fred_again_apple_music.html").read_text())


def fred_again_reaction_payload(*, position: int = 2) -> dict[str, Any]:
    """Dashboard ``toggleReaction`` POST body for a Fred Again virtual track."""
    golden = load_fred_again_expected()
    entry = golden["entries"][position - 1]
    return {
        "entity_type": "set_entry",
        "entity_key": reaction_entity_key(golden["set_key"], position),
        "reaction": "heart",
        "source_url": golden["container_url"],
        "active": True,
        "attrs": {
            "set_key": golden["set_key"],
            "position": position,
            "timestamp_seconds": entry["start_seconds"],
        },
    }


def assert_all_platform_refs(entry: SetEntry) -> None:
    schemas = {ref.schema_id for ref in entry.source_refs}
    assert schemas == {PLATFORM_YOUTUBE, PLATFORM_1001TL, PLATFORM_APPLE}
