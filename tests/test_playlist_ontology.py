"""YouTube playlist fan-out: Apple album overlap then catalog ontology."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from maya_graph.music.normalize import artist_refs
from maya_graph.music.primitives import CanonicalWork, SourceRef
from services.discord.playlist import PlaylistExpansion
from services.music.playlist_ontology import (
    apply_playlist_ontology,
    resolve_playlist_ontology,
    _simple_ratio,
    _title_ratio,
)


def test_token_set_ratio_is_too_loose_for_short_titles() -> None:
    assert _title_ratio("Flip.", "Fanoodle (Flip)") >= 90
    assert _simple_ratio("Flip.", "Fanoodle (Flip)") < 90
    assert _simple_ratio("Listen.", "Listen") >= 90


def _album(cid: str, title: str, artist: str) -> CanonicalWork:
    return CanonicalWork(
        key=f"apple_music:album/{cid}",
        label=title,
        artists=artist_refs(artist),
        anchors=(
            SourceRef(
                schema="apple_music",
                external_id=f"album/{cid}",
                url=f"https://music.apple.com/us/album/{cid}",
            ),
        ),
        attrs={"kind": "album"},
    )


def _song(track_id: str, title: str, artist: str, album: str, collection_id: str) -> CanonicalWork:
    return CanonicalWork(
        key=f"apple_music:{track_id}",
        label=title,
        artists=artist_refs(artist),
        anchors=(
            SourceRef(
                schema="apple_music",
                external_id=str(track_id),
                url=f"https://music.apple.com/us/song/{track_id}",
            ),
            SourceRef(schema="apple_music", external_id=f"album/{collection_id}"),
        ),
        attrs={"album": album},
    )


@pytest.mark.asyncio
async def test_playlist_ontology_picks_album_by_track_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    sasqadia = _album("1483430195", "Siuslaw", "Sasqadia")
    pheel = _album("6798847099", "siuslaw", "pheel.")
    monkeypatch.setattr(
        "services.music.playlist_ontology.search_album",
        AsyncMock(return_value=[sasqadia, pheel]),
    )

    async def _lookup(cid, **_kwargs):
        if str(cid) == "6798847099":
            return pheel, [
                _song("6798847100", "Listen.", "pheel.", "siuslaw.", "6798847099"),
                _song("6798847101", "Doppler.", "pheel.", "siuslaw.", "6798847099"),
            ]
        return sasqadia, [
            _song("1483430196", "Marys Peak", "Sasqadia", "Siuslaw", "1483430195"),
        ]

    monkeypatch.setattr(
        "services.music.playlist_ontology.lookup_collection_songs",
        _lookup,
    )
    expansion = PlaylistExpansion(
        title="siuslaw.",
        tracks=[
            ("https://www.youtube.com/watch?v=W2M_yWPYlYA", "listen."),
            ("https://www.youtube.com/watch?v=QkYd0Smae-A", "doppler."),
        ],
        playlist_id="OLAK5uy_mcs9iYWN2LEM-J7drMBsjBYJhbmE544rQ",
        video_ids=["W2M_yWPYlYA", "QkYd0Smae-A"],
    )
    onto = await resolve_playlist_ontology(
        "https://youtube.com/playlist?list=OLAK5uy_mcs9iYWN2LEM-J7drMBsjBYJhbmE544rQ",
        expansion,
        deep=False,
        ingest=False,
    )
    assert onto is not None
    assert onto.artist == "pheel"
    assert onto.album_work is not None
    assert "6798847099" in onto.album_work.key
    assert onto.tracks[0].work_key == "apple_music:6798847100"
    assert onto.tracks[0].video_id == "W2M_yWPYlYA"
    schemas = {ref["schema_id"] for ref in onto.tracks[0].source_refs}
    assert "apple_music" in schemas
    assert "yt" in schemas
    assert onto.tracks[0].work_key.startswith("apple_music:")
    artifact = apply_playlist_ontology(
        {
            "type": "playlist",
            "title": "siuslaw.",
            "tracks": [
                {"title": "listen.", "query": expansion.tracks[0][0], "src": "/x"},
                {"title": "doppler.", "query": expansion.tracks[1][0], "src": "/x"},
            ],
        },
        onto,
    )
    assert artifact["artist"] == "pheel"
    assert artifact["tracks"][0]["query"].startswith("https://www.youtube.com/watch")
    assert artifact["tracks"][0]["work_key"] == "apple_music:6798847100"


@pytest.mark.asyncio
async def test_deep_map_keeps_apple_when_catalog_title_diverges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``token_set_ratio`` scores Flip ⊂ Fanoodle (Flip) as 100; keep Apple instead."""
    pheel = _album("6798847099", "siuslaw", "pheel.")
    flip = _song("6798847102", "Flip.", "pheel.", "siuslaw.", "6798847099")
    monkeypatch.setattr(
        "services.music.playlist_ontology.search_album",
        AsyncMock(return_value=[pheel]),
    )

    async def _lookup(cid, **_kwargs):
        return pheel, [flip]

    monkeypatch.setattr(
        "services.music.playlist_ontology.lookup_collection_songs",
        _lookup,
    )
    steal = CanonicalWork(
        key="mb:recording/c153e7ef-ffff-ffff-ffff-ffffffffffff",
        label="Fanoodle (Flip)",
        artists=artist_refs("Someone Else"),
        anchors=(
            SourceRef(
                schema="mb",
                external_id="recording/c153e7ef-ffff-ffff-ffff-ffffffffffff",
            ),
        ),
    )

    async def _map(_parsed, _schemas, extra_works=()):
        return steal

    monkeypatch.setattr("services.music.playlist_ontology.map_identity", _map)
    expansion = PlaylistExpansion(
        title="siuslaw.",
        tracks=[("https://www.youtube.com/watch?v=abcdefghijk", "flip.")],
        playlist_id="OLAK5uy_example",
        video_ids=["abcdefghijk"],
    )
    onto = await resolve_playlist_ontology(
        "https://youtube.com/playlist?list=OLAK5uy_example",
        expansion,
        deep=True,
        ingest=False,
    )
    assert onto is not None
    assert onto.tracks[0].work_key == "apple_music:6798847102"
    assert onto.tracks[0].title == "Flip."
    schemas = {ref["schema_id"] for ref in onto.tracks[0].source_refs}
    assert "apple_music" in schemas
    assert "yt" in schemas
    assert "mb" not in schemas


@pytest.mark.asyncio
async def test_deep_map_keeps_catalog_when_titles_agree(monkeypatch: pytest.MonkeyPatch) -> None:
    pheel = _album("6798847099", "siuslaw", "pheel.")
    listen = _song("6798847100", "Listen.", "pheel.", "siuslaw.", "6798847099")
    monkeypatch.setattr(
        "services.music.playlist_ontology.search_album",
        AsyncMock(return_value=[pheel]),
    )

    async def _lookup(cid, **_kwargs):
        return pheel, [listen]

    monkeypatch.setattr(
        "services.music.playlist_ontology.lookup_collection_songs",
        _lookup,
    )
    catalog = CanonicalWork(
        key="wd:Q999",
        label="Listen",
        artists=artist_refs("pheel."),
        anchors=(
            SourceRef(schema="wd", external_id="Q999"),
            SourceRef(schema="apple_music", external_id="6798847100"),
        ),
    )

    async def _map(_parsed, _schemas, extra_works=()):
        return catalog

    monkeypatch.setattr("services.music.playlist_ontology.map_identity", _map)
    expansion = PlaylistExpansion(
        title="siuslaw.",
        tracks=[("https://www.youtube.com/watch?v=W2M_yWPYlYA", "listen.")],
        video_ids=["W2M_yWPYlYA"],
    )
    onto = await resolve_playlist_ontology(
        "https://youtube.com/playlist?list=x",
        expansion,
        deep=True,
        ingest=False,
    )
    assert onto is not None
    assert onto.tracks[0].work_key == "wd:Q999"
    schemas = {ref["schema_id"] for ref in onto.tracks[0].source_refs}
    assert "wd" in schemas
    assert "apple_music" in schemas
    assert "yt" in schemas


@pytest.mark.asyncio
async def test_build_playlist_fans_out_ontology(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.dashboard.player import build_playlist_for_query
    from services.music.playlist_ontology import PlaylistOntology, PlaylistTrackOntology

    expansion = PlaylistExpansion(
        title="siuslaw.",
        tracks=[
            ("https://www.youtube.com/watch?v=W2M_yWPYlYA", "listen."),
            ("https://www.youtube.com/watch?v=QkYd0Smae-A", "doppler."),
        ],
        playlist_id="OLAK5uy_example",
        video_ids=["W2M_yWPYlYA", "QkYd0Smae-A"],
    )
    monkeypatch.setattr("services.music.url_handler.detect_platform", lambda _u: None)
    monkeypatch.setattr(
        "services.music.ontology.resolve_for_play",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr("services.discord.playlist.expand_playlist", lambda _q: expansion)

    onto = PlaylistOntology(
        artist="pheel.",
        album_title="siuslaw.",
        album_work=_album("6798847099", "siuslaw.", "pheel."),
        overlap=1.0,
        tracks=[
            PlaylistTrackOntology(
                title="Listen.",
                url=expansion.tracks[0][0],
                video_id="W2M_yWPYlYA",
                artist="pheel.",
                work_key="apple_music:6798847100",
                work=None,
                source_refs=[
                    {"schema_id": "yt", "external_id": "W2M_yWPYlYA", "url": expansion.tracks[0][0]},
                    {"schema_id": "apple_music", "external_id": "6798847100", "url": None},
                ],
            ),
            PlaylistTrackOntology(
                title="Doppler.",
                url=expansion.tracks[1][0],
                video_id="QkYd0Smae-A",
                artist="pheel.",
                work_key="apple_music:6798847101",
                work=None,
                source_refs=[],
            ),
        ],
        source_refs=[],
    )
    monkeypatch.setattr(
        "services.music.playlist_ontology.resolve_playlist_ontology",
        AsyncMock(return_value=onto),
    )
    playlist = await build_playlist_for_query(
        "https://youtube.com/playlist?list=OLAK5uy_example",
        ontology_deep=True,
    )
    assert playlist["artist"] == "pheel."
    assert playlist["tracks"][0]["work_key"] == "apple_music:6798847100"
    assert "youtube.com/watch" in playlist["tracks"][0]["query"]


@pytest.mark.asyncio
async def test_youtube_playlist_skips_set_index_and_plays_watch_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.dashboard.player import build_playlist_for_query
    from services.music.playlist_ontology import PlaylistOntology, PlaylistTrackOntology

    expansion = PlaylistExpansion(
        title="siuslaw.",
        tracks=[
            ("https://www.youtube.com/watch?v=W2M_yWPYlYA", "listen."),
            ("https://www.youtube.com/watch?v=QkYd0Smae-A", "doppler."),
        ],
        playlist_id="OLAK5uy_example",
        video_ids=["W2M_yWPYlYA", "QkYd0Smae-A"],
    )

    async def _index(*_args, **_kwargs):
        raise AssertionError("YouTube playlist URLs must expand, not index as DJ sets")

    monkeypatch.setattr("services.music.url_handler.detect_platform", lambda _u: "youtube")
    monkeypatch.setattr("services.music.url_handler.index_music_url", _index)
    monkeypatch.setattr(
        "services.music.ontology.resolve_for_play",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr("services.discord.playlist.expand_playlist", lambda _q: expansion)
    monkeypatch.setattr(
        "services.music.playlist_ontology.resolve_playlist_ontology",
        AsyncMock(
            return_value=PlaylistOntology(
                artist="pheel.",
                album_title="siuslaw.",
                album_work=_album("6798847099", "siuslaw.", "pheel."),
                overlap=1.0,
                tracks=[
                    PlaylistTrackOntology(
                        title="Listen.",
                        url=expansion.tracks[0][0],
                        video_id="W2M_yWPYlYA",
                        artist="pheel.",
                        work_key="apple_music:6798847100",
                        work=None,
                        source_refs=[
                            {
                                "schema_id": "yt",
                                "external_id": "W2M_yWPYlYA",
                                "url": expansion.tracks[0][0],
                            }
                        ],
                    ),
                    PlaylistTrackOntology(
                        title="Doppler.",
                        url=expansion.tracks[1][0],
                        video_id="QkYd0Smae-A",
                        artist="pheel.",
                        work_key="apple_music:6798847101",
                        work=None,
                        source_refs=[],
                    ),
                ],
            )
        ),
    )
    playlist = await build_playlist_for_query(
        "https://youtube.com/playlist?list=OLAK5uy_example"
    )
    assert playlist["presentation"] == "playlist"
    assert playlist["tracks"][0]["query"] == expansion.tracks[0][0]
    assert playlist["tracks"][0]["work_key"] == "apple_music:6798847100"
