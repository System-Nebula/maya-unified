"""Cross-platform Fred Again merge tests."""

from __future__ import annotations

from services.music.set_correlate import correlate_sets
from services.music.set_types import PLATFORM_1001TL, PLATFORM_APPLE, PLATFORM_YOUTUBE

from tests.helpers.music_set_fixtures import (
    fred_again_1001tl_resolved,
    fred_again_apple_resolved,
    fred_again_merged_resolved_set,
    fred_again_youtube_resolved,
)
from tests.tracklists.conftest import assert_entry_source_schemas, assert_set_contract


def test_fred_again_three_platform_parsed_sets():
    yt = fred_again_youtube_resolved()
    tl = fred_again_1001tl_resolved()
    apple = fred_again_apple_resolved()
    for resolved in (yt, tl, apple):
        assert_set_contract(resolved)
    assert len(yt.entries) == 3
    assert len(tl.entries) == 3
    assert len(apple.entries) == 3


def test_fred_again_pairwise_merge_all_platforms():
    merged = fred_again_merged_resolved_set()
    assert_set_contract(merged)
    assert merged.container_schema == PLATFORM_YOUTUBE
    assert len(merged.entries) == 3
    assert len(merged.linked_sets) >= 2
    for entry in merged.entries:
        assert_entry_source_schemas(
            entry,
            {PLATFORM_YOUTUBE, PLATFORM_1001TL, PLATFORM_APPLE},
        )


def test_fred_again_varargs_correlate_prefers_youtube_container():
    """Three-arg correlate merges YT base with best pool match per entry (pairwise fold is canonical)."""
    yt = fred_again_youtube_resolved()
    tl = fred_again_1001tl_resolved()
    apple = fred_again_apple_resolved()
    varargs = correlate_sets(yt, tl, apple)
    assert varargs.container_schema == PLATFORM_YOUTUBE
    assert len(varargs.entries) == 3
    for entry in varargs.entries:
        schemas = {r.schema_id for r in entry.source_refs}
        assert PLATFORM_YOUTUBE in schemas
        assert PLATFORM_1001TL in schemas
