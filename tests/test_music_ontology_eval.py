"""Music ontology evaluation tests — Andrea Botez DJ mix golden path.

Manual playhead verification checklist (dashboard sticky player):
1. Load playlist with 26 virtual tracks sharing one stream URL.
2. On track change, player seeks to ``start_offset`` via ``_seekToOffset``.
3. At ``end_offset - 0.25s``, ``onTime`` auto-advances to the next track.
4. Reactions use ``entity_type=set_entry`` and ``entity_key={set_key}:{position}``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from helpers.music_set_fixtures import (
    ANDREA_URL,
    ANDREA_URL_CANONICAL,
    andrea_resolved_set,
    assert_golden_entries,
    load_andrea_description,
    load_andrea_expected,
    load_andrea_ytdlp_info,
    reaction_entity_key,
)
from maya_contracts import SourceRefModel, TrackMetadata
from maya_feeds.youtube_setlist import parse_tracklist_lines, parse_youtube_set_from_info
from services.cmd.executors.play import exec_play
from services.cmd.models import CmdContext, CmdSurface
from services.music.set_ingest import enrich_set_entries
from services.music.set_playlist import build_playlist_from_set
from services.music.url_handler import PLATFORM_YOUTUBE, fetch_and_parse_url


# ---------------------------------------------------------------------------
# Layer A: Parser golden path
# ---------------------------------------------------------------------------


def test_andrea_parser_matches_golden_fixture():
    golden = load_andrea_expected()
    description = load_andrea_description()
    entries = parse_tracklist_lines(description, duration_seconds=golden["duration_seconds"])
    assert_golden_entries(entries, golden["entries"])
    assert len(entries) == 26


def test_andrea_brisa_boundary_timestamps():
    golden = load_andrea_expected()
    brisa = golden["entries"][3]
    assert brisa["start_seconds"] == 4 * 60 + 34
    assert brisa["end_seconds"] == 6 * 60 + 42


def test_andrea_last_track_end_equals_duration():
    golden = load_andrea_expected()
    description = load_andrea_description()
    entries = parse_tracklist_lines(description, duration_seconds=golden["duration_seconds"])
    last = entries[-1]
    assert last.start_seconds == 55 * 60 + 30
    assert last.end_seconds == golden["duration_seconds"]


def test_parse_youtube_set_from_info_matches_golden():
    golden = load_andrea_expected()
    info = load_andrea_ytdlp_info()
    parsed = parse_youtube_set_from_info(info)
    assert parsed is not None
    assert parsed.video_id == golden["video_id"]
    assert len(parsed.entries) == golden["track_count"]
    assert_golden_entries(parsed.entries, golden["entries"])


# ---------------------------------------------------------------------------
# Layer B: URL handler → ResolvedSet (mock yt-dlp)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_and_parse_url_ignores_playlist_param(monkeypatch):
    ytdlp_info = load_andrea_ytdlp_info()
    monkeypatch.setattr(
        "services.music.url_handler._fetch_youtube_info",
        lambda _url: ytdlp_info,
    )
    resolved = await fetch_and_parse_url(ANDREA_URL)
    assert resolved is not None
    assert resolved.set_key == f"{PLATFORM_YOUTUBE}:u1NHX9FcHVw"
    assert len(resolved.entries) == 26
    assert resolved.container_url == ANDREA_URL_CANONICAL


# ---------------------------------------------------------------------------
# Layer C: Playlist artifact — seek offsets and gapless contract
# ---------------------------------------------------------------------------


def test_andrea_playlist_artifact_seek_offsets_and_gapless():
    golden = load_andrea_expected()
    resolved = andrea_resolved_set()
    artifact = build_playlist_from_set(ANDREA_URL, resolved)

    assert artifact["type"] == "playlist"
    assert artifact["presentation"] == "set"
    assert artifact["mode"] == "live_set"
    assert artifact["video_id"] == golden["video_id"]
    assert len(artifact["entries"]) == 26
    assert artifact["set_key"] == golden["set_key"]
    tracks = artifact["tracks"]
    assert len(tracks) == 26

    stream_queries = {t["query"] for t in tracks}
    assert stream_queries == {resolved.container_url}

    for i, track in enumerate(tracks):
        row = golden["entries"][i]
        assert track["start_offset"] == row["start_seconds"]
        assert track["end_offset"] == row["end_seconds"]
        assert track["position"] == row["position"]
        assert track["play_mode"] == "seek"
        assert track["set_key"] == golden["set_key"]
        assert track["duration"] == max(0, row["end_seconds"] - row["start_seconds"])
        assert track["src"].startswith("/api/media/stream?q=")

    for i in range(len(tracks) - 1):
        assert tracks[i]["end_offset"] == tracks[i + 1]["start_offset"], f"gap at track {i + 1}"


def test_playhead_reaction_entity_key_contract():
    golden = load_andrea_expected()
    set_key = golden["set_key"]
    assert reaction_entity_key(set_key, 4) == f"{set_key}:4"


# ---------------------------------------------------------------------------
# Layer E: Async enrichment fan-out (mock-only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_playlist_for_query_schedules_background_ingest(monkeypatch):
    resolved = andrea_resolved_set()
    scheduled: list[object] = []

    async def fake_index(_url, *, ingest=False, correlate=True):
        return resolved

    def fake_create_task(coro):
        scheduled.append(coro)
        coro.close()
        return MagicMock()

    monkeypatch.setattr("services.music.url_handler.index_music_url", fake_index)
    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    from services.dashboard.player import build_playlist_for_query

    artifact = await build_playlist_for_query(ANDREA_URL)
    assert len(artifact["tracks"]) == 26
    assert artifact["tracks"][0]["start_offset"] == 0
    assert len(scheduled) == 1


@pytest.mark.asyncio
async def test_enrich_set_entries_attaches_work_keys_from_lookup(monkeypatch):
    resolved = andrea_resolved_set()

    async def fake_lookup(query: str):
        if "Hard Bounce" in query:
            return TrackMetadata(
                title="Hard Bounce",
                work_key="fp:hard-bounce",
                source_refs=[
                    SourceRefModel(schema_id="wd", external_id="Q999", confidence=0.9)
                ],
                confidence=0.9,
            )
        return None

    monkeypatch.setattr("services.music.ontology.lookup", fake_lookup)

    enriched = await enrich_set_entries(resolved)
    first = enriched.entries[0]
    assert first.work_key == "fp:hard-bounce"
    schema_ids = {ref.schema_id for ref in first.source_refs}
    assert PLATFORM_YOUTUBE in schema_ids
    assert "wd" in schema_ids


# ---------------------------------------------------------------------------
# Layer F: /play — setlist URL routes through build_playlist_for_query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exec_play_youtube_setlist_url_uses_tracklist_path(monkeypatch):
    """Dashboard /play should resolve DJ set URLs to virtual tracks with offsets."""
    import sys
    import types

    fake_hub = types.ModuleType("services.voice.hub")

    class _Hub:
        ready = False
        agent = None

        @staticmethod
        def broadcast(_event, *, operator_id=None, room_id=None):
            return None

    fake_hub.hub = _Hub()
    monkeypatch.setitem(sys.modules, "services.voice.hub", fake_hub)

    captured_playlists: list[dict] = []

    def capture_load(playlist, *, operator_id=None, corr_id=None):
        captured_playlists.append(playlist)

    monkeypatch.setattr("services.dashboard.player.broadcast_player_load", capture_load)

    resolved = andrea_resolved_set()

    async def fake_index(_url, *, ingest=False, correlate=True):
        return resolved

    monkeypatch.setattr("services.music.url_handler.index_music_url", fake_index)
    monkeypatch.setattr(asyncio, "create_task", lambda coro: (coro.close(), MagicMock())[1])

    result = await exec_play(
        CmdContext(surface=CmdSurface.DASHBOARD, raw_text=f"/play {ANDREA_URL}"),
        {},
    )
    assert result.ok is True
    assert "26 tracks" in (result.text or "")
    assert "live set" in (result.text or "")
    assert result.artifacts
    assert result.artifacts[0]["presentation"] == "set"

    assert len(captured_playlists) == 1
    artifact = captured_playlists[0]
    assert artifact["presentation"] == "set"
    assert artifact["mode"] == "live_set"
    assert artifact["video_id"] == "u1NHX9FcHVw"
    assert len(artifact["entries"]) == 26
    tracks = artifact["tracks"]
    assert len(tracks) == 26
    assert tracks[0]["start_offset"] == 0


@pytest.mark.asyncio
async def test_exec_play_double_play_prefix_resolves_setlist(monkeypatch):
    """``/play /play <url>`` should normalize to the URL, not treat ``/play url`` as title."""
    import sys
    import types

    fake_hub = types.ModuleType("services.voice.hub")

    class _Hub:
        ready = False
        agent = None

        @staticmethod
        def broadcast(_event, *, operator_id=None, room_id=None):
            return None

    fake_hub.hub = _Hub()
    monkeypatch.setitem(sys.modules, "services.voice.hub", fake_hub)

    captured_playlists: list[dict] = []

    def capture_load(playlist, *, operator_id=None, corr_id=None):
        captured_playlists.append(playlist)

    monkeypatch.setattr("services.dashboard.player.broadcast_player_load", capture_load)

    resolved = andrea_resolved_set()

    async def fake_index(url, *, ingest=False, correlate=True):
        assert url == ANDREA_URL_CANONICAL or url == ANDREA_URL
        return resolved

    monkeypatch.setattr("services.music.url_handler.index_music_url", fake_index)
    monkeypatch.setattr(asyncio, "create_task", lambda coro: (coro.close(), MagicMock())[1])

    result = await exec_play(
        CmdContext(
            surface=CmdSurface.DASHBOARD,
            raw_text=f"/play /play {ANDREA_URL}",
        ),
        {},
    )
    assert result.ok is True
    assert "26 tracks" in (result.text or "")
    assert "live set" in (result.text or "")
    assert captured_playlists[0]["presentation"] == "set"
    resolved = andrea_resolved_set()

    async def fake_index(_url, *, ingest=False, correlate=True):
        return resolved

    monkeypatch.setattr("services.music.url_handler.index_music_url", fake_index)
    monkeypatch.setattr(asyncio, "create_task", lambda coro: (coro.close(), MagicMock())[1])

    from services.dashboard.player import build_playlist_for_query

    artifact = await build_playlist_for_query(ANDREA_URL)
    assert len(artifact["tracks"]) == 26
    assert artifact["tracks"][0]["start_offset"] == 0
    assert artifact["tracks"][3]["start_offset"] == 4 * 60 + 34
    assert artifact["set_key"] == f"{PLATFORM_YOUTUBE}:u1NHX9FcHVw"
