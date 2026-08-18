"""Catalog schema adapters + identity mapping (mocked HTTP, no live catalogs)."""

from __future__ import annotations

import httpx
import pytest

from maya_graph.music.catalog import map_identity
from maya_graph.music.normalize import ParsedTrack, artist_refs
from maya_graph.music.primitives import CanonicalWork, SourceRef, WorkQuery
from maya_graph.music.schemas.discogs import DiscogsSchema
from maya_graph.music.schemas.itunes import ItunesSchema
from maya_graph.music.schemas.musicbrainz import MusicBrainzSchema
from maya_graph.music.schemas.wikidata import WikidataSchema


class _UrlTransport(httpx.AsyncBaseTransport):
    def __init__(self, routes: dict[str, dict]) -> None:
        self._routes = routes

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host_path = request.url.host + request.url.path
        for key, payload in self._routes.items():
            if key in host_path:
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={})


@pytest.mark.asyncio
async def test_musicbrainz_search_maps_recording_and_isrc() -> None:
    recording_id = "77c9ba93-2d8e-4e2c-9a0a-0c0b6d0c0b6d"
    artist_id = "db92a151-1ac2-438b-bc43-b82e149ddd50"
    transport = _UrlTransport(
        {
            "musicbrainz.org": {
                "recordings": [
                    {
                        "id": recording_id,
                        "title": "Never Gonna Give You Up",
                        "artist-credit": [
                            {
                                "name": "Rick Astley",
                                "artist": {"id": artist_id, "name": "Rick Astley"},
                            }
                        ],
                        "isrcs": ["GBARL9300135"],
                    }
                ]
            }
        }
    )
    client = httpx.AsyncClient(transport=transport)
    works = await MusicBrainzSchema(client=client).search_work(
        WorkQuery(text="Never Gonna Give You Up", artist="Rick Astley")
    )
    assert works
    work = works[0]
    assert work.label == "Never Gonna Give You Up"
    assert work.artists[0].name == "Rick Astley"
    keys = {a.domain_key() for a in work.anchors}
    assert f"mb:recording/{recording_id}" in keys
    assert "isrc:GBARL9300135" in keys


@pytest.mark.asyncio
async def test_discogs_search_maps_master() -> None:
    transport = _UrlTransport(
        {
            "api.discogs.com": {
                "results": [
                    {
                        "id": 249504,
                        "type": "release",
                        "master_id": 96559,
                        "title": "Rick Astley - Never Gonna Give You Up",
                        "year": "1987",
                        "uri": "/release/249504-Rick-Astley-Never-Gonna-Give-You-Up",
                    }
                ]
            }
        }
    )
    client = httpx.AsyncClient(transport=transport)
    works = await DiscogsSchema(client=client).search_work(
        WorkQuery(text="Never Gonna Give You Up", artist="Rick Astley")
    )
    assert works[0].key == "discogs:master/96559"
    assert works[0].artists[0].name == "Rick Astley"
    assert any(a.external_id == "master/96559" for a in works[0].anchors)
    release = next(a for a in works[0].anchors if a.external_id.startswith("release/"))
    assert release.url == "https://www.discogs.com/release/249504-Rick-Astley-Never-Gonna-Give-You-Up"


@pytest.mark.asyncio
async def test_itunes_search_maps_apple_music_and_isrc() -> None:
    transport = _UrlTransport(
        {
            "itunes.apple.com": {
                "results": [
                    {
                        "wrapperType": "track",
                        "trackId": 1440837612,
                        "trackName": "Never Gonna Give You Up",
                        "artistName": "Rick Astley",
                        "artistId": 336635001,
                        "collectionName": "Whenever You Need Somebody",
                        "collectionId": 1440837325,
                        "isrc": "GBARL9300135",
                        "trackViewUrl": "https://music.apple.com/us/song/never-gonna-give-you-up/1440837612",
                    }
                ]
            }
        }
    )
    client = httpx.AsyncClient(transport=transport)
    works = await ItunesSchema(client=client).search_work(
        WorkQuery(text="Never Gonna Give You Up", artist="Rick Astley")
    )
    work = works[0]
    assert work.key == "apple_music:1440837612"
    assert work.artists[0].name == "Rick Astley"
    assert work.attrs["album"] == "Whenever You Need Somebody"
    assert any(a.schema == "isrc" for a in work.anchors)


@pytest.mark.asyncio
async def test_map_identity_merges_catalog_anchors_and_keeps_canonical_names() -> None:
    mb = CanonicalWork(
        key="mb:recording/abc",
        label="Never Gonna Give You Up",
        artists=artist_refs("Rick Astley"),
        anchors=(SourceRef(schema="mb", external_id="recording/abc"),),
    )
    discogs = CanonicalWork(
        key="discogs:master/96559",
        label="Never Gonna Give You Up",
        artists=artist_refs("Rick Astley"),
        anchors=(SourceRef(schema="discogs", external_id="master/96559"),),
    )

    class _Stub:
        def __init__(self, schema_id: str, work: CanonicalWork) -> None:
            self.schema_id = schema_id
            self._work = work

        async def search_work(self, query: WorkQuery) -> list[CanonicalWork]:
            return [self._work]

        async def fetch_recording(self, ref):
            return None

        async def fetch_recordings(self, work):
            return []

    parsed = ParsedTrack(
        artist="rick astley",
        title="Never Gonna Give You Up",
        base_title="Never Gonna Give You Up",
    )
    mapped = await map_identity(parsed, [_Stub("mb", mb), _Stub("discogs", discogs)])
    assert mapped.key.startswith("mb:")
    assert mapped.label == "Never Gonna Give You Up"
    assert mapped.artists[0].name == "Rick Astley"
    keys = {a.domain_key() for a in mapped.anchors}
    assert "mb:recording/abc" in keys
    assert "discogs:master/96559" in keys


@pytest.mark.asyncio
async def test_map_identity_falls_back_to_fingerprint() -> None:
    class _Empty:
        schema_id = "mb"

        async def search_work(self, query: WorkQuery) -> list[CanonicalWork]:
            return []

        async def fetch_recording(self, ref):
            return None

        async def fetch_recordings(self, work):
            return []

    parsed = ParsedTrack(artist="Ivy Lab", title="Infinite Falling Ground", base_title="Infinite Falling Ground")
    mapped = await map_identity(parsed, [_Empty()])
    assert mapped.key.startswith("fp:")
    assert mapped.artists[0].name == "Ivy Lab"


@pytest.mark.asyncio
async def test_wikidata_search_attaches_musicbrainz_and_discogs() -> None:
    qid = "Q165109"

    def wbsearchentities(_params):
        return {
            "search": [
                {"id": qid, "label": "Never Gonna Give You Up", "aliases": [], "description": "song"}
            ]
        }

    def wbgetentities(params):
        ids = params.get("ids", "")
        if ids == qid:
            return {
                "entities": {
                    qid: {
                        "id": qid,
                        "labels": {"en": {"value": "Never Gonna Give You Up"}},
                        "claims": {
                            "P31": [
                                {
                                    "mainsnak": {
                                        "datavalue": {
                                            "type": "wikibase-entityid",
                                            "value": {"id": "Q7366"},
                                        }
                                    }
                                }
                            ],
                            "P175": [
                                {
                                    "mainsnak": {
                                        "datavalue": {
                                            "type": "wikibase-entityid",
                                            "value": {"id": "Q185724"},
                                        }
                                    }
                                }
                            ],
                            "P4404": [
                                {
                                    "mainsnak": {
                                        "datavalue": {
                                            "type": "string",
                                            "value": "77c9ba93-2d8e-4e2c-9a0a-0c0b6d0c0b6d",
                                        }
                                    }
                                }
                            ],
                            "P1954": [
                                {
                                    "mainsnak": {
                                        "datavalue": {"type": "string", "value": "96559"}
                                    }
                                }
                            ],
                        },
                    }
                }
            }
        if "Q185724" in ids:
            return {
                "entities": {
                    "Q185724": {
                        "id": "Q185724",
                        "labels": {"en": {"value": "Rick Astley"}},
                        "claims": {},
                    }
                }
            }
        return {"entities": {}}

    class _Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            action = dict(request.url.params).get("action", "")
            if action == "wbsearchentities":
                return httpx.Response(200, json=wbsearchentities(dict(request.url.params)))
            if action == "wbgetentities":
                return httpx.Response(200, json=wbgetentities(dict(request.url.params)))
            return httpx.Response(404, json={})

    schema = WikidataSchema(client=httpx.AsyncClient(transport=_Transport()))
    works = await schema.search_work(
        WorkQuery(text="Never Gonna Give You Up", artist="Rick Astley")
    )
    work = works[0]
    assert work.key == f"wd:{qid}"
    assert work.artists[0].name == "Rick Astley"
    keys = {a.domain_key() for a in work.anchors}
    assert f"wd:{qid}" in keys
    assert "mb:recording/77c9ba93-2d8e-4e2c-9a0a-0c0b6d0c0b6d" in keys
    assert "discogs:master/96559" in keys


@pytest.mark.asyncio
async def test_wikidata_searches_title_not_artist_concat() -> None:
    seen: list[str] = []

    class _Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            params = dict(request.url.params)
            if params.get("action") == "wbsearchentities":
                seen.append(params.get("search", ""))
                return httpx.Response(200, json={"search": []})
            return httpx.Response(200, json={"entities": {}})

    await WikidataSchema(client=httpx.AsyncClient(transport=_Transport())).search_work(
        WorkQuery(text="Never Gonna Give You Up", artist="Rick Astley")
    )
    assert seen == ["Never Gonna Give You Up"]


@pytest.mark.asyncio
async def test_wikidata_skips_nonsong_then_matches_performer() -> None:
    xbox = "Q48263"
    song = "Q126033982"
    artist = "Q13590"

    def _entity(qid: str, p31: str, performer: str | None = None) -> dict:
        claims = {
            "P31": [
                {
                    "mainsnak": {
                        "datavalue": {"type": "wikibase-entityid", "value": {"id": p31}}
                    }
                }
            ]
        }
        if performer:
            claims["P175"] = [
                {
                    "mainsnak": {
                        "datavalue": {
                            "type": "wikibase-entityid",
                            "value": {"id": performer},
                        }
                    }
                }
            ]
        return {"id": qid, "labels": {"en": {"value": qid}}, "claims": claims}

    class _Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            params = dict(request.url.params)
            action = params.get("action", "")
            if action == "wbsearchentities":
                return httpx.Response(
                    200,
                    json={
                        "search": [
                            {"id": xbox, "label": "Xbox 360", "description": "console"},
                            {
                                "id": song,
                                "label": "360",
                                "description": "2024 single by Charli XCX",
                            },
                        ]
                    },
                )
            if action == "wbgetentities":
                ids = params.get("ids", "")
                entities = {}
                if xbox in ids:
                    entities[xbox] = _entity(xbox, "Q8075")
                if song in ids:
                    entities[song] = _entity(song, "Q134556", artist)
                if artist in ids:
                    entities[artist] = {
                        "id": artist,
                        "labels": {"en": {"value": "Charli XCX"}},
                        "claims": {},
                    }
                return httpx.Response(200, json={"entities": entities})
            return httpx.Response(404, json={})

    works = await WikidataSchema(client=httpx.AsyncClient(transport=_Transport())).search_work(
        WorkQuery(text="360", artist="Charli XCX")
    )
    assert works[0].key == f"wd:{song}"
    assert works[0].artists[0].name == "Charli XCX"


@pytest.mark.asyncio
async def test_wikidata_search_release_prefers_album_parenthetical() -> None:
    seen: list[str] = []
    qid = "Q124691269"

    class _Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            params = dict(request.url.params)
            action = params.get("action", "")
            if action == "wbsearchentities":
                seen.append(params.get("search", ""))
                return httpx.Response(
                    200,
                    json={
                        "search": [
                            {
                                "id": qid,
                                "label": "Brat",
                                "description": "2024 studio album by Charli XCX",
                            }
                        ]
                    },
                )
            if action == "wbgetentities":
                return httpx.Response(
                    200,
                    json={
                        "entities": {
                            qid: {
                                "id": qid,
                                "labels": {"en": {"value": "Brat"}},
                                "claims": {
                                    "P31": [
                                        {
                                            "mainsnak": {
                                                "datavalue": {
                                                    "type": "wikibase-entityid",
                                                    "value": {"id": "Q208569"},
                                                }
                                            }
                                        }
                                    ]
                                },
                            }
                        }
                    },
                )
            return httpx.Response(404, json={})

    works = await WikidataSchema(client=httpx.AsyncClient(transport=_Transport())).search_release(
        WorkQuery(text="Brat", artist="Charli XCX")
    )
    assert seen[0] == "Brat (album)"
    assert works[0].key == f"wd:{qid}"


@pytest.mark.asyncio
async def test_itunes_album_harvests_song_collection() -> None:
    transport = _UrlTransport(
        {
            "itunes.apple.com": {
                "results": [
                    {
                        "wrapperType": "track",
                        "trackId": 1739079976,
                        "trackName": "360",
                        "artistName": "Charli xcx",
                        "artistId": 319375941,
                        "collectionName": "BRAT",
                        "collectionId": 1739079974,
                        "collectionViewUrl": "https://music.apple.com/us/album/brat/1739079974",
                    }
                ]
            }
        }
    )
    client = httpx.AsyncClient(transport=transport)
    from maya_graph.music.schemas.itunes import search_album

    works = await search_album("Charli XCX", "Brat", client=client)
    assert works[0].key == "apple_music:album/1739079974"
    assert works[0].label == "BRAT"
    assert works[0].anchors[0].url == "https://music.apple.com/us/album/brat/1739079974"


@pytest.mark.asyncio
async def test_map_identity_reuses_extra_works_without_requery() -> None:
    mb = CanonicalWork(
        key="mb:recording/abc",
        label="360",
        artists=artist_refs("Charli XCX"),
        anchors=(SourceRef(schema="mb", external_id="recording/abc"),),
    )

    class _Boom:
        schema_id = "mb"

        async def search_work(self, query: WorkQuery) -> list[CanonicalWork]:
            raise AssertionError("MusicBrainz should not be queried again")

        async def fetch_recording(self, ref):
            return None

        async def fetch_recordings(self, work):
            return []

    parsed = ParsedTrack(artist="Charli XCX", title="360", base_title="360")
    mapped = await map_identity(parsed, [_Boom()], extra_works=(mb,))
    assert mapped.key == "mb:recording/abc"
