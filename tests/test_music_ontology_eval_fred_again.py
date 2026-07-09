"""Fred Again cross-platform music ontology evaluation (edge 2).

1001tracklists, Apple Music, and YouTube deep-link to the same DJ set.
Reactions target ``set_entry`` rows keyed ``yt:gfF8jzBVWvM:{position}``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from helpers.music_set_fixtures import (
    FRED_AGAIN_1001TL_URL,
    FRED_AGAIN_APPLE_URL,
    FRED_AGAIN_SET_KEY,
    FRED_AGAIN_YT_URL,
    assert_all_platform_refs,
    fred_again_1001tl_resolved,
    fred_again_apple_resolved,
    fred_again_merged_resolved_set,
    fred_again_reaction_payload,
    fred_again_youtube_resolved,
    load_fred_again_expected,
    reaction_entity_key,
    seed_fred_again_fetch_cache,
)
from maya_contracts import PlayResolveRequest
from services.music.set_playlist import build_playlist_from_set
from services.music.url_cache import cache_clear
from services.music.url_handler import (
    PLATFORM_1001TL,
    PLATFORM_APPLE,
    PLATFORM_YOUTUBE,
    index_music_url,
)


@pytest.fixture(autouse=True)
def _clear_url_cache():
    cache_clear()
    yield
    cache_clear()


# ---------------------------------------------------------------------------
# A. Parser golden path
# ---------------------------------------------------------------------------


def test_fred_again_1001tl_fixture_linked_urls():
    resolved = fred_again_1001tl_resolved()
    assert len(resolved.entries) == 3
    urls = [ref.url for ref in resolved.linked_sets if ref.url]
    assert any("youtube.com/watch?v=gfF8jzBVWvM" in u for u in urls)
    assert any("music.apple.com" in u for u in urls)


def test_fred_again_apple_fixture_track_ids_and_links():
    resolved = fred_again_apple_resolved()
    assert len(resolved.entries) == 3
    assert resolved.entries[0].source_refs[0].external_id == "1890298648"
    urls = [ref.url for ref in resolved.linked_sets if ref.url]
    assert any("youtube.com" in u for u in urls)
    assert any("1001tracklists.com" in u for u in urls)


def test_fred_again_youtube_description_three_entries():
    resolved = fred_again_youtube_resolved()
    assert len(resolved.entries) == 3
    assert resolved.entries[0].start_seconds == 0
    assert resolved.entries[1].start_seconds == 5 * 60 + 12


def test_fred_again_merged_matches_golden():
    golden = load_fred_again_expected()
    merged = fred_again_merged_resolved_set()
    assert merged.set_key == golden["set_key"]
    assert merged.container_url == golden["container_url"]
    assert len(merged.entries) == golden["track_count"]
    for entry, row in zip(merged.entries, golden["entries"], strict=True):
        assert entry.position == row["position"]
        assert entry.start_seconds == row["start_seconds"]
        assert sorted({r.schema_id for r in entry.source_refs}) == row["source_ref_schemas"]


# ---------------------------------------------------------------------------
# B. index_music_url from each seed URL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "seed_url",
    [FRED_AGAIN_1001TL_URL, FRED_AGAIN_APPLE_URL, FRED_AGAIN_YT_URL],
)
async def test_index_music_url_from_each_seed_merges_three_platforms(seed_url: str):
    seed_fred_again_fetch_cache()
    result = await index_music_url(seed_url, correlate=True, ingest=False)
    assert result is not None
    assert result.set_key == FRED_AGAIN_SET_KEY
    assert result.container_url == FRED_AGAIN_YT_URL
    assert len(result.entries) == 3
    for entry in result.entries:
        assert_all_platform_refs(entry)

    trace = result.attrs.get("fetch_trace") or {}
    assert len(trace.get("fetched_urls") or []) == 3
    assert set(trace.get("platforms") or []) == {PLATFORM_YOUTUBE, PLATFORM_1001TL, PLATFORM_APPLE}


# ---------------------------------------------------------------------------
# C. Playlist + play resolve
# ---------------------------------------------------------------------------


def test_fred_again_playlist_three_seek_tracks_shared_stream():
    merged = fred_again_merged_resolved_set()
    artifact = build_playlist_from_set(FRED_AGAIN_1001TL_URL, merged)
    assert len(artifact["tracks"]) == 3
    queries = {t["query"] for t in artifact["tracks"]}
    assert queries == {FRED_AGAIN_YT_URL}
    assert artifact["tracks"][0]["start_offset"] == 0
    assert artifact["tracks"][1]["start_offset"] == 312
    assert artifact["tracks"][0]["end_offset"] == artifact["tracks"][1]["start_offset"]


@pytest.mark.asyncio
async def test_play_resolve_fred_again_setlist(monkeypatch):
    merged = fred_again_merged_resolved_set()
    monkeypatch.setattr(
        "services.music.url_handler.index_music_url",
        AsyncMock(return_value=merged),
    )
    from maya_gateway.services.ontology_resolve import resolve_with_ontology

    resp = await resolve_with_ontology(PlayResolveRequest(query=FRED_AGAIN_1001TL_URL))
    assert resp.matched_via == "setlist"
    assert len(resp.tracks) == 3
    assert resp.tracks[1].track_id == f"{FRED_AGAIN_SET_KEY}:2"
    assert resp.tracks[1].start_offset_seconds == 312


# ---------------------------------------------------------------------------
# D. Playback enrichment contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_playlist_for_query_schedules_ingest(monkeypatch):
    merged = fred_again_merged_resolved_set()
    scheduled: list[object] = []

    async def fake_index(_url, *, ingest=False, correlate=True):
        return merged

    def fake_create_task(coro):
        scheduled.append(coro)
        coro.close()
        return MagicMock()

    monkeypatch.setattr("services.music.url_handler.index_music_url", fake_index)
    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    from services.dashboard.player import build_playlist_for_query

    artifact = await build_playlist_for_query(FRED_AGAIN_1001TL_URL)
    assert len(artifact["tracks"]) == 3
    assert artifact["set_key"] == FRED_AGAIN_SET_KEY
    assert len(scheduled) == 1


def test_music_index_url_voice_tool():
    import sys
    from pathlib import Path
    from unittest.mock import patch

    merged = fred_again_merged_resolved_set()
    _vr = Path(__file__).resolve().parents[1] / "packages" / "voice-runtime"
    if str(_vr) not in sys.path:
        sys.path.insert(0, str(_vr))
    from tools.music_ontology import build_music_ontology_tools

    tools = build_music_ontology_tools()
    handler = next(t for t in tools if t.name == "music_index_url")
    with patch("services.music.url_handler.index_music_url_sync", return_value=merged):
        out = handler.handler({"url": FRED_AGAIN_1001TL_URL, "correlate": True})
    assert out["found"] is True
    assert out["entry_count"] == 3
    assert out["set_key"] == FRED_AGAIN_SET_KEY


# ---------------------------------------------------------------------------
# E. Reaction contract
# ---------------------------------------------------------------------------


def test_fred_again_reaction_entity_key():
    assert reaction_entity_key(FRED_AGAIN_SET_KEY, 2) == f"{FRED_AGAIN_SET_KEY}:2"


def test_fred_again_reaction_post_body_shape():
    payload = fred_again_reaction_payload(position=2)
    assert payload["entity_type"] == "set_entry"
    assert payload["entity_key"] == f"{FRED_AGAIN_SET_KEY}:2"
    assert payload["attrs"]["timestamp_seconds"] == 312
    assert payload["source_url"] == FRED_AGAIN_YT_URL
