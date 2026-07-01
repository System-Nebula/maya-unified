"""Tests for DnB play resolver entries."""

import pytest
from maya_contracts import PlayResolveRequest

from maya_gateway.services.discogs import DiscogsClient
from maya_gateway.services.play_resolve import resolve


class EmptyDiscogs(DiscogsClient):
    def fetch_master(self, master_id: int):  # noqa: ANN001
        return None


@pytest.fixture()
def empty_discogs() -> EmptyDiscogs:
    return EmptyDiscogs()


@pytest.mark.parametrize(
    "query",
    [
        "[IVY] & A Little Sound - Can't Love Me",
        "ivy - can't love me",
        "little sound can't love me",
        "ukf can't love me",
    ],
)
def test_cant_love_me_matches(query: str, empty_discogs: EmptyDiscogs) -> None:
    resp = resolve(PlayResolveRequest(query=query), discogs=empty_discogs)
    assert resp.tracks, f"expected match for {query!r}"
    top = resp.tracks[0]
    assert top.title == "Can't Love Me"
    assert "IVY" in top.artist
    assert top.stream_url is not None
    assert "4waehYAY6qM" in top.stream_url
    assert top.watch_url == "https://youtu.be/4waehYAY6qM"
