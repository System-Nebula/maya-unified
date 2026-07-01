"""Paginated walk of a YouTube channel's uploads playlist.

The uploads playlist ID is always the channel ID with `UC` → `UU` prefix.
``playlistItems.list`` returns 50 entries per call (1 quota unit) and a
``nextPageToken`` for resumable iteration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, Optional

import httpx


_API = "https://www.googleapis.com/youtube/v3/playlistItems"
_VIDEOS_API = "https://www.googleapis.com/youtube/v3/videos"


@dataclass(frozen=True)
class CatalogueEntry:
    video_id: str
    title: str
    description: Optional[str]
    published_at: datetime
    thumbnail_url: Optional[str]


@dataclass(frozen=True)
class CataloguePage:
    entries: list[CatalogueEntry]
    next_page_token: Optional[str]


def uploads_playlist_id(channel_id: str) -> str:
    if channel_id.startswith("UC"):
        return "UU" + channel_id[2:]
    return channel_id


async def fetch_page(
    channel_id: str,
    page_token: Optional[str] = None,
    api_key: Optional[str] = None,
    http: Optional[httpx.AsyncClient] = None,
) -> CataloguePage:
    key = api_key or os.getenv("YOUTUBE_API_KEY")
    if not key:
        return CataloguePage(entries=[], next_page_token=None)
    params = {
        "part": "snippet,contentDetails",
        "playlistId": uploads_playlist_id(channel_id),
        "maxResults": 50,
        "key": key,
    }
    if page_token:
        params["pageToken"] = page_token
    client = http or httpx.AsyncClient(timeout=30.0)
    try:
        resp = await client.get(_API, params=params)
        resp.raise_for_status()
        data = resp.json()
    finally:
        if http is None:
            await client.aclose()
    entries: list[CatalogueEntry] = []
    for item in data.get("items", []):
        snip = item.get("snippet", {})
        cd = item.get("contentDetails", {})
        published = _parse_dt(cd.get("videoPublishedAt") or snip.get("publishedAt"))
        if published is None:
            continue
        thumbs = (snip.get("thumbnails") or {})
        thumb = (
            (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url")
        )
        entries.append(
            CatalogueEntry(
                video_id=cd.get("videoId") or snip.get("resourceId", {}).get("videoId"),
                title=snip.get("title", ""),
                description=snip.get("description"),
                published_at=published,
                thumbnail_url=thumb,
            )
        )
    return CataloguePage(entries=entries, next_page_token=data.get("nextPageToken"))


async def walk_catalogue(
    channel_id: str,
    start_token: Optional[str] = None,
    max_pages: Optional[int] = None,
    api_key: Optional[str] = None,
) -> AsyncIterator[CataloguePage]:
    token = start_token
    pages = 0
    async with httpx.AsyncClient(timeout=30.0) as http:
        while True:
            page = await fetch_page(channel_id, token, api_key, http)
            yield page
            pages += 1
            if max_pages is not None and pages >= max_pages:
                return
            if not page.next_page_token:
                return
            token = page.next_page_token


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None
