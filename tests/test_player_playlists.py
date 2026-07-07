"""Tests for dashboard playlist persistence and smart playlist helpers."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from services.dashboard.playlists import get_playlist, list_playlists, save_playlist
from services.dashboard.smart_playlist import _suggestion_to_track, stream_smart_playlist


def test_suggestion_to_track_builds_query() -> None:
    tr = _suggestion_to_track({"artist": "Artist", "title": "Song"}, 0)
    assert tr["artist"] == "Artist"
    assert tr["title"] == "Song"
    assert tr["query"] == "Artist Song"


def test_save_and_list_playlists(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("services.dashboard.playlists.DATA", tmp_path)
    saved = save_playlist(
        "op-1",
        name="Test Mix",
        tracks=[{"title": "A", "artist": "B", "query": "B A"}],
    )
    items = list_playlists("op-1")
    assert len(items) == 1
    assert items[0]["name"] == "Test Mix"
    loaded = get_playlist("op-1", saved["id"])
    assert loaded["tracks"][0]["query"] == "B A"


@pytest.mark.asyncio
async def test_stream_smart_playlist_fallback_on_llm_error() -> None:
    events: list[tuple[str, dict]] = []

    def emit(event: str, data: dict) -> None:
        events.append((event, data))

    with patch(
        "services.dashboard.smart_playlist._llm_plan",
        new_callable=AsyncMock,
        side_effect=RuntimeError("offline"),
    ):
        await stream_smart_playlist("drum and bass", emit, operator_id="op-1")

    track_events = [e for e in events if e[0] == "track"]
    assert len(track_events) >= 1
    assert track_events[0][1]["query"]
