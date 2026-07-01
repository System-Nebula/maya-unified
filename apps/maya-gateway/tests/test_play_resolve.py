"""Unit tests for the demo play resolver."""

from __future__ import annotations

from typing import Optional

import pytest
from maya_contracts import PlayResolveRequest, VideoRef

from maya_gateway.services.discogs import DiscogsClient, DiscogsMaster
from maya_gateway.services.play_resolve import resolve


class StubDiscogs(DiscogsClient):
    """In-memory DiscogsClient — never touches the network."""

    def __init__(self, masters: dict[int, DiscogsMaster]) -> None:
        super().__init__()
        self._masters = masters

    def fetch_master(self, master_id: int) -> Optional[DiscogsMaster]:
        return self._masters.get(master_id)


@pytest.fixture()
def empty_discogs() -> StubDiscogs:
    return StubDiscogs({})


@pytest.fixture()
def rick_discogs() -> StubDiscogs:
    return StubDiscogs(
        {
            96559: DiscogsMaster(
                master_id=96559,
                title="Never Gonna Give You Up",
                year=1987,
                main_release=249504,
                artists=["Rick Astley"],
                videos=[
                    VideoRef(
                        youtube_id="dQw4w9WgXcQ",
                        title="Rick Astley - Never Gonna Give You Up (Official Video)",
                        duration_seconds=214.0,
                        embed_url="https://www.youtube.com/embed/dQw4w9WgXcQ?enablejsapi=1",
                        watch_url="https://youtu.be/dQw4w9WgXcQ",
                    ),
                ],
            )
        }
    )


@pytest.mark.parametrize(
    "query",
    [
        "Rick Astley - Never Gonna Give You Up",
        "rick astley - never gonna give you up",
        "risk astley - never going to give you up",
        "Never Gonna Give You Up",
    ],
)
def test_rick_astley_matches(query: str, empty_discogs: StubDiscogs) -> None:
    resp = resolve(PlayResolveRequest(query=query), discogs=empty_discogs)
    assert resp.tracks, "expected at least one track"
    top = resp.tracks[0]
    assert top.artist == "Rick Astley"
    assert top.title == "Never Gonna Give You Up"
    # Resolver should hand back the public YouTube embed for the canonical clip
    # plus a canonical watch_url so the UI can fall back gracefully when the
    # uploader has disabled embedded playback (YouTube IFrame error 150).
    assert top.stream_url is not None
    assert "dQw4w9WgXcQ" in top.stream_url
    assert top.watch_url == "https://youtu.be/dQw4w9WgXcQ"


def test_query_and_zone_echo_back(empty_discogs: StubDiscogs) -> None:
    resp = resolve(
        PlayResolveRequest(query="lofi hip hop radio", zone="lab"),
        discogs=empty_discogs,
    )
    assert resp.zone == "lab"
    assert resp.query == "lofi hip hop radio"
    assert resp.tracks[0].artist == "Lofi Girl"


def test_match_via_classification(empty_discogs: StubDiscogs) -> None:
    exact = resolve(PlayResolveRequest(query="Departure"), discogs=empty_discogs)
    assert exact.matched_via in {"exact", "fuzzy"}
    assert exact.tracks[0].title == "Departure"
    assert exact.tracks[0].stream_url is not None
    assert exact.tracks[0].watch_url is not None


def test_discogs_enrichment_attaches_master_and_videos(
    rick_discogs: StubDiscogs,
) -> None:
    resp = resolve(
        PlayResolveRequest(query="rick astley - never gonna give you up"),
        discogs=rick_discogs,
    )
    top = resp.tracks[0]

    # Discogs master reference is wired up — this is the property graph edge
    # back into the ontology.
    assert top.discogs is not None
    assert top.discogs.master_id == 96559
    assert top.discogs.release_id == 249504
    assert top.discogs.year == 1987
    assert top.discogs.url == "https://www.discogs.com/master/96559"

    # videos[] is harvested from the master's videos[] edge.
    assert len(top.videos) == 1
    v = top.videos[0]
    assert v.youtube_id == "dQw4w9WgXcQ"
    assert "dQw4w9WgXcQ" in v.embed_url
    assert v.watch_url == "https://youtu.be/dQw4w9WgXcQ"
    assert v.source == "discogs"


def test_discogs_failure_still_pins_master_ref(empty_discogs: StubDiscogs) -> None:
    """When Discogs is unreachable, we still link the master_id so the UI can deeplink."""
    resp = resolve(
        PlayResolveRequest(query="rick astley - never gonna give you up"),
        discogs=empty_discogs,
    )
    top = resp.tracks[0]
    assert top.discogs is not None
    assert top.discogs.master_id == 96559
    assert top.discogs.url == "https://www.discogs.com/master/96559"
    # No videos enriched (empty stub returns None for the master).
    assert top.videos == []
