"""Tests for cross-source DJ set correlation."""

from __future__ import annotations

from pathlib import Path

from maya_contracts import SourceRefModel
from maya_feeds.apple_music import parse_apple_music_html
from maya_feeds.tracklists_1001 import parse_1001tracklists_html
from maya_feeds.youtube_setlist import parse_youtube_set_from_info

from services.music.set_correlate import correlate_sets
from services.music.set_types import PLATFORM_1001TL, PLATFORM_APPLE, PLATFORM_YOUTUBE, ResolvedSet, SetEntry
from tests.helpers.music_set_fixtures import (
    FIXTURES,
    fred_again_1001tl_resolved,
    fred_again_apple_resolved,
    fred_again_youtube_resolved,
)


def _yt_set() -> ResolvedSet:
    return ResolvedSet(
        set_key=f"{PLATFORM_YOUTUBE}:gfF8jzBVWvM",
        title="Fred again.. live",
        container_url="https://www.youtube.com/watch?v=gfF8jzBVWvM",
        container_schema=PLATFORM_YOUTUBE,
        entries=[
            SetEntry(
                position=1,
                start_seconds=0,
                end_seconds=312,
                label="Turn On The Lights again..",
                artist="Fred again..",
                title="Turn On The Lights again..",
                source_refs=[
                    SourceRefModel(schema_id=PLATFORM_YOUTUBE, external_id="gfF8jzBVWvM#1", confidence=1.0)
                ],
            ),
            SetEntry(
                position=2,
                start_seconds=312,
                end_seconds=720,
                label="Trax On Da Rocks Vol. 1",
                artist="Thomas Bangalter",
                title="Trax On Da Rocks Vol. 1",
                source_refs=[
                    SourceRefModel(schema_id=PLATFORM_YOUTUBE, external_id="gfF8jzBVWvM#2", confidence=1.0)
                ],
            ),
        ],
    )


def _apple_set() -> ResolvedSet:
    return ResolvedSet(
        set_key=f"{PLATFORM_APPLE}:1890298647",
        title="Alexandra Palace DJ Mix",
        container_url="https://music.apple.com/us/album/alexandra-palace-london-feb-27-2026-dj-mix/1890298647",
        container_schema=PLATFORM_APPLE,
        entries=[
            SetEntry(
                position=1,
                start_seconds=0,
                end_seconds=300,
                label="Turn On The Lights again..",
                artist=None,
                title="Turn On The Lights again..",
                source_refs=[
                    SourceRefModel(schema_id=PLATFORM_APPLE, external_id="1890298648", confidence=1.0)
                ],
            ),
            SetEntry(
                position=2,
                start_seconds=300,
                end_seconds=720,
                label="Trax On Da Rocks Vol. 1",
                artist=None,
                title="Trax On Da Rocks Vol. 1",
                source_refs=[
                    SourceRefModel(schema_id=PLATFORM_APPLE, external_id="1890298649", confidence=1.0)
                ],
            ),
        ],
    )


def test_correlate_youtube_and_apple_merges_source_refs():
    merged = correlate_sets(_yt_set(), _apple_set())
    assert merged.container_schema == PLATFORM_YOUTUBE
    assert len(merged.entries) == 2
    assert len(merged.entries[0].source_refs) == 2
    schemas = {ref.schema_id for ref in merged.entries[0].source_refs}
    assert PLATFORM_YOUTUBE in schemas
    assert PLATFORM_APPLE in schemas
    assert len(merged.linked_sets) >= 1


def _fred_again_youtube_resolved() -> ResolvedSet:
    return fred_again_youtube_resolved()


def _fred_again_1001tl_resolved() -> ResolvedSet:
    return fred_again_1001tl_resolved()


def _fred_again_apple_resolved() -> ResolvedSet:
    return fred_again_apple_resolved()


def test_correlate_fred_again_three_fixtures_parsed():
    """Chain-parse YT description + 1001TL + Apple fixtures; correlate cross-source."""
    yt = _fred_again_youtube_resolved()
    tl = _fred_again_1001tl_resolved()
    apple = _fred_again_apple_resolved()

    assert len(yt.entries) == 3
    assert len(tl.entries) == 3
    assert len(apple.entries) == 3

    merged = correlate_sets(yt, tl, apple)
    assert merged.container_schema == PLATFORM_YOUTUBE
    assert len(merged.entries) == 3
    assert len(merged.linked_sets) >= 2

    for entry in merged.entries:
        schemas = {ref.schema_id for ref in entry.source_refs}
        assert PLATFORM_YOUTUBE in schemas
        assert PLATFORM_1001TL in schemas

    # Pairwise merge with Apple succeeds; chained merge yields all three platforms.
    all_platforms = correlate_sets(correlate_sets(yt, tl), apple)
    for entry in all_platforms.entries:
        schemas = {ref.schema_id for ref in entry.source_refs}
        assert schemas == {PLATFORM_YOUTUBE, PLATFORM_1001TL, PLATFORM_APPLE}
