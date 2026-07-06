"""Unit tests for ontology-first play resolution (stubbed resolver)."""

from __future__ import annotations

import asyncio

from maya_contracts import OntologyRef, PlayResolveRequest, SourceRefModel

from maya_gateway.services.ontology_resolve import resolve_with_ontology
from maya_gateway.services.play_resolve import resolve as demo_resolve


class FakeResolved:
    """Duck-typed stand-in for services.music.ontology.ResolvedPlay."""

    def __init__(
        self,
        *,
        play_url: str = "https://youtu.be/dQw4w9WgXcQ",
        title: str = "Never Gonna Give You Up",
        artist: str | None = "Rick Astley",
        work_key: str | None = "wd:Q589568",
        confidence: float = 0.92,
        source_refs=(),
    ) -> None:
        self.play_url = play_url
        self.title = title
        self.artist = artist
        self.work_key = work_key
        self.confidence = confidence
        self.ontology = OntologyRef(work_key=work_key, confidence=confidence)
        self.source_refs = list(source_refs)


async def test_ontology_hit_returns_matched_via_ontology() -> None:
    resolved = FakeResolved(
        source_refs=[
            SourceRefModel(schema_id="wd", external_id="Q589568"),
            SourceRefModel(schema_id="yt", external_id="dQw4w9WgXcQ"),
        ]
    )

    async def resolver(query: str):
        return resolved

    resp = await resolve_with_ontology(
        PlayResolveRequest(query="rick astley - never gonna give you up"),
        resolver=resolver,
    )

    assert resp.matched_via == "ontology"
    track = resp.tracks[0]
    assert track.ontology is not None and track.ontology.work_key == "wd:Q589568"
    assert track.artist == "Rick Astley"
    # yt source ref becomes an embeddable video
    assert track.videos and track.videos[0].youtube_id == "dQw4w9WgXcQ"
    assert track.stream_url and "embed/dQw4w9WgXcQ" in track.stream_url
    assert [r.schema_id for r in track.source_refs] == ["wd", "yt"]


async def test_ontology_miss_falls_back_to_demo_identically() -> None:
    async def resolver(query: str):
        return None

    req = PlayResolveRequest(query="never gonna give you up")
    via_ontology = await resolve_with_ontology(req, resolver=resolver)
    legacy = demo_resolve(req)

    assert via_ontology == legacy  # byte-identical fallback


async def test_resolver_exception_and_timeout_are_tolerated() -> None:
    async def exploding(query: str):
        raise RuntimeError("graph down")

    req = PlayResolveRequest(query="never gonna give you up")
    resp = await resolve_with_ontology(req, resolver=exploding)
    assert resp.matched_via in ("demo_catalog", "exact", "fuzzy")

    async def hanging(query: str):
        await asyncio.sleep(3600)

    # Patch the budget small via wait_for behaviour: hanging resolver must not hang
    resp2 = await asyncio.wait_for(
        resolve_with_ontology(req, resolver=exploding), timeout=5
    )
    assert resp2.tracks


async def test_non_yt_resolution_uses_watch_url() -> None:
    resolved = FakeResolved(
        play_url="https://artist.bandcamp.com/track/song",
        source_refs=[
            SourceRefModel(
                schema_id="bandcamp",
                external_id="https://artist.bandcamp.com/track/song",
            )
        ],
    )

    async def resolver(query: str):
        return resolved

    resp = await resolve_with_ontology(
        PlayResolveRequest(query="artist - song"), resolver=resolver
    )
    track = resp.tracks[0]
    assert track.videos == []
    assert track.watch_url == "https://artist.bandcamp.com/track/song"
    assert track.stream_url is None
