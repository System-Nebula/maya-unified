"""MusicBrainz source schema — recording/artist MBIDs + ISRCs.

Uses the public JSON WS (https://musicbrainz.org/ws/2). Best-effort: empty
list on timeout, 503, or a miss. A User-Agent is required by MusicBrainz.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from maya_graph.music.normalize import artist_refs, clean_name
from maya_graph.music.primitives import CanonicalWork, Recording, SourceRef, WorkQuery

logger = logging.getLogger(__name__)

MUSICBRAINZ_API = "https://musicbrainz.org/ws/2/recording/"
USER_AGENT = "maya-unified-music/1.0 (https://github.com/System-Nebula/maya-unified)"
_TIMEOUT_SEC = 4.0


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _artist_credit_name(payload: dict[str, Any]) -> str | None:
    names: list[str] = []
    for credit in payload.get("artist-credit") or []:
        if not isinstance(credit, dict):
            continue
        name = credit.get("name") or (credit.get("artist") or {}).get("name")
        if name:
            names.append(str(name))
    return clean_name(" ".join(names)) if names else None


def _artist_mbids(payload: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for credit in payload.get("artist-credit") or []:
        if not isinstance(credit, dict):
            continue
        artist = credit.get("artist") or {}
        mbid = artist.get("id")
        if mbid:
            out.append(str(mbid))
    return out


def _work_from_recording(payload: dict[str, Any]) -> CanonicalWork | None:
    recording_id = payload.get("id")
    title = clean_name(str(payload.get("title") or "")) or payload.get("title")
    if not recording_id or not title:
        return None
    artist_name = _artist_credit_name(payload)
    anchors = [
        SourceRef(
            schema="mb",
            external_id=f"recording/{recording_id}",
            url=f"https://musicbrainz.org/recording/{recording_id}",
        )
    ]
    for mbid in _artist_mbids(payload):
        anchors.append(
            SourceRef(
                schema="mb",
                external_id=f"artist/{mbid}",
                url=f"https://musicbrainz.org/artist/{mbid}",
            )
        )
    isrcs = [str(code) for code in (payload.get("isrcs") or []) if code]
    for isrc in isrcs[:3]:
        anchors.append(SourceRef(schema="isrc", external_id=isrc))
    releases = payload.get("releases") or []
    album = None
    if releases and isinstance(releases[0], dict):
        album = clean_name(str(releases[0].get("title") or ""))
        rg = (releases[0].get("release-group") or {}).get("id")
        if rg:
            anchors.append(
                SourceRef(
                    schema="mb",
                    external_id=f"release-group/{rg}",
                    url=f"https://musicbrainz.org/release-group/{rg}",
                )
            )
    length_ms = payload.get("length")
    duration = int(length_ms / 1000) if isinstance(length_ms, (int, float)) else None
    return CanonicalWork(
        key=f"mb:recording/{recording_id}",
        label=str(title),
        artists=artist_refs(artist_name),
        anchors=tuple(anchors),
        attrs={
            "album": album,
            "isrc": isrcs[0] if isrcs else None,
            "duration_seconds": duration,
            "score": payload.get("score"),
        },
    )


class MusicBrainzSchema:
    schema_id = "mb"

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def search_work(self, query: WorkQuery) -> list[CanonicalWork]:
        title = (query.text or "").strip()
        artist = (query.artist or "").strip()
        if not title and not artist:
            return []
        clauses: list[str] = []
        if title:
            clauses.append(f'recording:"{_quote(title)}"')
        if artist:
            clauses.append(f'artist:"{_quote(artist)}"')
        lucene = " AND ".join(clauses)
        try:
            if self._client is not None:
                return await self._search(self._client, lucene)
            async with httpx.AsyncClient(
                timeout=_TIMEOUT_SEC,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            ) as client:
                return await self._search(client, lucene)
        except (TimeoutError, httpx.HTTPError) as exc:
            logger.warning("musicbrainz search failed for %r: %s", lucene, exc)
            return []

    async def fetch_recording(self, ref: SourceRef) -> Recording | None:
        return None

    async def fetch_recordings(self, work: CanonicalWork) -> list[Recording]:
        return []

    async def _search(self, client: httpx.AsyncClient, lucene: str) -> list[CanonicalWork]:
        resp = await client.get(
            MUSICBRAINZ_API,
            params={
                "query": lucene,
                "fmt": "json",
                "limit": 5,
            },
        )
        if resp.status_code != 200:
            return []
        works: list[CanonicalWork] = []
        for payload in resp.json().get("recordings") or []:
            if not isinstance(payload, dict):
                continue
            work = _work_from_recording(payload)
            if work is not None:
                works.append(work)
        return works
