"""OTEL spans for YouTube playlist expansion into the sticky player."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.discord.playlist import PlaylistExpansion


@pytest.mark.asyncio
async def test_youtube_playlist_expand_records_spans(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry import trace
    from services.dashboard.player import build_playlist_for_query
    from services.tracing import attach_in_memory_exporter, span_records

    expansion = PlaylistExpansion(
        title="Example Album",
        tracks=[
            ("https://www.youtube.com/watch?v=aaaaaaaaaaa", "Track 1"),
            ("https://www.youtube.com/watch?v=bbbbbbbbbbb", "Track 2"),
        ],
    )
    monkeypatch.setattr("services.music.url_handler.detect_platform", lambda _u: None)
    monkeypatch.setattr(
        "services.music.ontology.resolve_for_play",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr("services.discord.playlist.expand_playlist", lambda _q: expansion)

    exporter, previous = attach_in_memory_exporter("maya-play-playlist-probe")
    try:
        url = (
            "https://youtube.com/playlist?list="
            "OLAK5uy_mcs9iYWN2LEM-J7drMBsjBYJhbmE544rQ"
        )
        playlist = await build_playlist_for_query(url)
        provider = trace.get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush()
        records = span_records(exporter)
        names = [row["name"] for row in records]
        assert "play.build_playlist" in names
        assert "play.expand_playlist" in names
        expand = next(row for row in records if row["name"] == "play.expand_playlist")
        assert expand["attributes"].get("track_count") == 2
        assert expand["attributes"].get("title") == "Example Album"
        assert playlist["presentation"] == "playlist"
        assert playlist["title"] == "Example Album"
        assert len(playlist["tracks"]) == 2
    finally:
        from services.tracing import restore_tracer_provider

        restore_tracer_provider(previous)
