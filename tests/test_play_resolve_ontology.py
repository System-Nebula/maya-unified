"""Tests for ontology-first play resolution (route-level consolidation).

Ontology-first resolution lives at the route level
(``maya_gateway.services.ontology_resolve.resolve_with_ontology``);
``play_resolve.resolve`` stays a pure offline demo resolver.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from maya_contracts import PlayResolveRequest, TrackInfo

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from maya_gateway.services.discogs import DiscogsClient  # noqa: E402
from maya_gateway.services.ontology_resolve import resolve_with_ontology  # noqa: E402
from maya_gateway.services.play_resolve import resolve  # noqa: E402


class StubDiscogs(DiscogsClient):
    def fetch_master(self, master_id: int):
        return None


@pytest.fixture()
def empty_discogs() -> StubDiscogs:
    return StubDiscogs()


def _demo_fallback(discogs: StubDiscogs):
    return lambda req: resolve(req, discogs=discogs)


async def test_ontology_hit_returns_matched_via_ontology(empty_discogs: StubDiscogs) -> None:
    from services.music.ontology import ResolvedPlay

    resolved = ResolvedPlay(
        play_url="https://youtu.be/abc123xyz12",
        title="Midnight City",
        artist="M83",
        work_key="wd:Q1",
        confidence=0.9,
        ontology=None,
        source_refs=(),
    )

    async def resolver(query: str):
        return resolved

    resp = await resolve_with_ontology(
        PlayResolveRequest(query="M83 - Midnight City"),
        resolver=resolver,
        fallback=_demo_fallback(empty_discogs),
    )
    assert resp.matched_via == "ontology"
    assert resp.tracks
    assert resp.tracks[0].title == "Midnight City"
    assert resp.tracks[0].artist == "M83"
    # youtube id extracted from play_url even without a yt source ref
    assert "abc123xyz12" in (resp.tracks[0].stream_url or "")


async def test_ontology_miss_falls_back_to_demo_catalog(empty_discogs: StubDiscogs) -> None:
    async def resolver(query: str):
        return None

    resp = await resolve_with_ontology(
        PlayResolveRequest(query="Rick Astley - Never Gonna Give You Up"),
        resolver=resolver,
        fallback=_demo_fallback(empty_discogs),
    )
    assert resp.matched_via in ("exact", "fuzzy", "demo_catalog")
    assert resp.tracks[0].artist == "Rick Astley"


async def test_ontology_exception_falls_back(empty_discogs: StubDiscogs) -> None:
    async def resolver(query: str):
        raise RuntimeError("boom")

    resp = await resolve_with_ontology(
        PlayResolveRequest(query="Rick Astley - Never Gonna Give You Up"),
        resolver=resolver,
        fallback=_demo_fallback(empty_discogs),
    )
    assert resp.tracks
    assert resp.matched_via != "ontology"


def test_demo_resolver_stays_pure_offline(empty_discogs: StubDiscogs) -> None:
    """resolve() must never consult the ontology (route owns that tier)."""
    resp = resolve(
        PlayResolveRequest(query="Never Gonna Give You Up"), discogs=empty_discogs
    )
    assert resp.matched_via in ("exact", "fuzzy", "demo_catalog")
    assert resp.tracks[0].artist == "Rick Astley"


def test_track_info_back_compat_without_ontology_fields() -> None:
    info = TrackInfo(track_id="t1", title="Song", artist="Artist")
    assert info.ontology is None
    assert info.source_refs == []
