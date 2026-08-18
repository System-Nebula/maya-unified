"""Discogs source schema — master/release identity from the public search API."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from maya_graph.music.normalize import artist_refs, clean_name, split_artist_title
from maya_graph.music.primitives import CanonicalWork, Recording, SourceRef, WorkQuery

logger = logging.getLogger(__name__)

DISCOGS_SEARCH = "https://api.discogs.com/database/search"
USER_AGENT = "maya-unified-music/1.0 (+https://github.com/System-Nebula/maya-unified)"
_TIMEOUT_SEC = 4.0


def _discogs_url(uri: str | None, fallback: str) -> str:
    if not uri:
        return fallback
    text = str(uri).strip()
    if text.startswith("https://") or text.startswith("http://"):
        return text
    if text.startswith("/"):
        return f"https://www.discogs.com{text}"
    return fallback


def _headers() -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    token = os.environ.get("DISCOGS_TOKEN")
    if token:
        headers["Authorization"] = f"Discogs token={token}"
    return headers


def _work_from_result(payload: dict[str, Any]) -> CanonicalWork | None:
    master_id = payload.get("master_id") or (
        payload.get("id") if payload.get("type") == "master" else None
    )
    release_id = payload.get("id") if payload.get("type") == "release" else None
    if not master_id and not release_id:
        return None
    raw_title = str(payload.get("title") or "")
    artist, title = split_artist_title(raw_title)
    title = title or clean_name(raw_title) or raw_title
    if not title:
        return None
    year = payload.get("year")
    try:
        year_int = int(year) if year not in (None, "") else None
    except (TypeError, ValueError):
        year_int = None
    anchors: list[SourceRef] = []
    key = ""
    if master_id:
        key = f"discogs:master/{master_id}"
        anchors.append(
            SourceRef(
                schema="discogs",
                external_id=f"master/{master_id}",
                url=f"https://www.discogs.com/master/{master_id}",
            )
        )
    if release_id:
        if not key:
            key = f"discogs:release/{release_id}"
        anchors.append(
            SourceRef(
                schema="discogs",
                external_id=f"release/{release_id}",
                url=_discogs_url(
                    payload.get("uri"),
                    f"https://www.discogs.com/release/{release_id}",
                ),
            )
        )
    return CanonicalWork(
        key=key,
        label=title,
        artists=artist_refs(artist),
        anchors=tuple(anchors),
        attrs={
            "album": title if payload.get("type") in {"master", "release"} else None,
            "year": year_int,
            "format": payload.get("format"),
        },
    )


class DiscogsSchema:
    schema_id = "discogs"

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def search_work(self, query: WorkQuery) -> list[CanonicalWork]:
        title = (query.text or "").strip()
        artist = (query.artist or "").strip()
        if not title and not artist:
            return []
        params: dict[str, Any] = {"type": "release", "per_page": 5}
        if artist:
            params["artist"] = artist
        if title:
            params["track"] = title
        try:
            if self._client is not None:
                return await self._search(self._client, params)
            async with httpx.AsyncClient(timeout=_TIMEOUT_SEC, headers=_headers()) as client:
                return await self._search(client, params)
        except (TimeoutError, httpx.HTTPError) as exc:
            logger.warning("discogs search failed for %s: %s", params, exc)
            return []

    async def fetch_recording(self, ref: SourceRef) -> Recording | None:
        return None

    async def fetch_recordings(self, work: CanonicalWork) -> list[Recording]:
        return []

    async def _search(
        self, client: httpx.AsyncClient, params: dict[str, Any]
    ) -> list[CanonicalWork]:
        resp = await client.get(DISCOGS_SEARCH, params=params)
        if resp.status_code != 200:
            return []
        works: list[CanonicalWork] = []
        for payload in resp.json().get("results") or []:
            if not isinstance(payload, dict):
                continue
            work = _work_from_result(payload)
            if work is not None:
                works.append(work)
        return works
