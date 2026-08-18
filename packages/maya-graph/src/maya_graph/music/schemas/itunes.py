"""Apple Music / iTunes catalog schema via the public iTunes Search API.

No developer token. Track Adam IDs and ISRCs map onto ``apple_music`` and
``isrc`` source refs for the Postgres graph.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from maya_graph.music.normalize import artist_refs, clean_name
from maya_graph.music.primitives import CanonicalWork, Recording, SourceRef, WorkQuery
from maya_graph.projector import normalize_key

logger = logging.getLogger(__name__)

ITUNES_SEARCH = "https://itunes.apple.com/search"
USER_AGENT = "maya-unified-music/1.0 (+https://github.com/System-Nebula/maya-unified)"
_TIMEOUT_SEC = 4.0


def _work_from_track(payload: dict[str, Any]) -> CanonicalWork | None:
    track_id = payload.get("trackId")
    title = clean_name(str(payload.get("trackName") or "")) or payload.get("trackName")
    if not track_id or not title:
        return None
    artist = clean_name(str(payload.get("artistName") or ""))
    album = clean_name(str(payload.get("collectionName") or ""))
    isrc = payload.get("isrc") or None
    view = payload.get("trackViewUrl") or f"https://music.apple.com/us/song/{track_id}"
    anchors = [
        SourceRef(schema="apple_music", external_id=str(track_id), url=str(view)),
    ]
    artist_id = payload.get("artistId")
    if artist_id:
        anchors.append(
            SourceRef(
                schema="apple_music",
                external_id=f"artist/{artist_id}",
                url=payload.get("artistViewUrl") or None,
            )
        )
    collection_id = payload.get("collectionId")
    if collection_id:
        anchors.append(
            SourceRef(
                schema="apple_music",
                external_id=f"album/{collection_id}",
                url=payload.get("collectionViewUrl") or None,
            )
        )
    if isrc:
        anchors.append(SourceRef(schema="isrc", external_id=str(isrc)))
    duration_ms = payload.get("trackTimeMillis")
    duration = int(duration_ms / 1000) if isinstance(duration_ms, (int, float)) else None
    return CanonicalWork(
        key=f"apple_music:{track_id}",
        label=str(title),
        artists=artist_refs(artist),
        anchors=tuple(anchors),
        attrs={
            "album": album,
            "isrc": isrc,
            "duration_seconds": duration,
            "release_date": payload.get("releaseDate"),
        },
    )


def _titles_match(query: str, candidate: str) -> bool:
    left, right = normalize_key(query), normalize_key(candidate)
    return bool(left) and left == right


def _artists_match(query: str, candidate: str) -> bool:
    left, right = normalize_key(query), normalize_key(candidate)
    if not left or not right:
        return not query
    return left == right or left in right or right in left


def _work_from_album(payload: dict[str, Any]) -> CanonicalWork | None:
    collection_id = payload.get("collectionId")
    title = clean_name(str(payload.get("collectionName") or "")) or payload.get(
        "collectionName"
    )
    if not collection_id or not title:
        return None
    artist = clean_name(str(payload.get("artistName") or ""))
    raw_view = str(payload.get("collectionViewUrl") or "")
    if raw_view and "i=" not in raw_view:
        view = raw_view
    else:
        view = f"https://music.apple.com/us/album/{collection_id}"
    artist_id = payload.get("artistId")
    anchors = [
        SourceRef(schema="apple_music", external_id=f"album/{collection_id}", url=str(view)),
    ]
    if artist_id:
        anchors.append(
            SourceRef(
                schema="apple_music",
                external_id=f"artist/{artist_id}",
                url=payload.get("artistViewUrl") or None,
            )
        )
    return CanonicalWork(
        key=f"apple_music:album/{collection_id}",
        label=str(title),
        artists=artist_refs(artist),
        anchors=tuple(anchors),
        attrs={
            "kind": "album",
            "release_date": payload.get("releaseDate"),
        },
    )


async def search_album(
    artist: str,
    title: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[CanonicalWork]:
    """Resolve an LP/collection. ``entity=album`` often misses (Brat); harvest songs."""
    term = " ".join(part for part in (artist, title) if part).strip()
    if not term:
        return []

    async def _run(http: httpx.AsyncClient) -> list[CanonicalWork]:
        seen: set[str] = set()
        works: list[CanonicalWork] = []

        def _accept(payload: dict[str, Any]) -> None:
            work = _work_from_album(payload)
            if work is None or work.key in seen:
                return
            if title and not _titles_match(title, work.label):
                return
            if artist and work.artists and not any(_artists_match(artist, a.name) for a in work.artists):
                return
            seen.add(work.key)
            works.append(work)

        song = await http.get(
            ITUNES_SEARCH,
            params={"term": term, "entity": "song", "limit": 15},
        )
        if song.status_code == 200:
            for payload in song.json().get("results") or []:
                if isinstance(payload, dict):
                    _accept(payload)
        if works:
            return works
        album = await http.get(
            ITUNES_SEARCH,
            params={"term": term, "entity": "album", "limit": 15},
        )
        if album.status_code == 200:
            for payload in album.json().get("results") or []:
                if isinstance(payload, dict):
                    _accept(payload)
        return works

    try:
        if client is not None:
            return await _run(client)
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SEC,
            headers={"User-Agent": USER_AGENT},
        ) as http:
            return await _run(http)
    except (TimeoutError, httpx.HTTPError) as exc:
        logger.warning("itunes album search failed for %r: %s", term, exc)
        return []


class ItunesSchema:
    schema_id = "apple_music"

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def search_work(self, query: WorkQuery) -> list[CanonicalWork]:
        parts = [p for p in (query.artist, query.text) if p]
        term = " ".join(parts).strip()
        if not term:
            return []
        try:
            if self._client is not None:
                return await self._search(self._client, term)
            async with httpx.AsyncClient(
                timeout=_TIMEOUT_SEC,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                return await self._search(client, term)
        except (TimeoutError, httpx.HTTPError) as exc:
            logger.warning("itunes search failed for %r: %s", term, exc)
            return []

    async def fetch_recording(self, ref: SourceRef) -> Recording | None:
        return None

    async def fetch_recordings(self, work: CanonicalWork) -> list[Recording]:
        return []

    async def _search(self, client: httpx.AsyncClient, term: str) -> list[CanonicalWork]:
        resp = await client.get(
            ITUNES_SEARCH,
            params={"term": term, "entity": "song", "limit": 5},
        )
        if resp.status_code != 200:
            return []
        works: list[CanonicalWork] = []
        for payload in resp.json().get("results") or []:
            if not isinstance(payload, dict):
                continue
            if payload.get("wrapperType") not in (None, "track"):
                continue
            work = _work_from_track(payload)
            if work is not None:
                works.append(work)
        return works
