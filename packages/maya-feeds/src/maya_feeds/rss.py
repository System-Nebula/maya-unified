"""Generic RSS 2.0 feed adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import feedparser
import httpx
from maya_contracts import Platform

from maya_feeds.protocol import ChannelMetadata, FetchedComments, VideoEntry


class RssAdapter:
    platform = Platform.RSS

    def __init__(self, http: Optional[httpx.AsyncClient] = None) -> None:
        self._http = http or httpx.AsyncClient(timeout=20.0, follow_redirects=True)

    async def _fetch_text(self, url: str) -> str:
        resp = await self._http.get(url, headers={"User-Agent": "maya-feeds/1.0 (RSS)"})
        resp.raise_for_status()
        return resp.text

    async def resolve_channel(self, handle: str) -> ChannelMetadata:
        feed_url = handle if handle.startswith("http") else f"https://{handle}"
        parsed = urlparse(feed_url)
        host = parsed.hostname or "unknown"
        path = parsed.path or "/"
        return ChannelMetadata(
            platform=Platform.RSS,
            platform_id=feed_url,
            handle=feed_url,
            display_name=f"RSS {host}{path}",
            feed_url=feed_url,
        )

    async def list_recent_videos(
        self, channel: ChannelMetadata, limit: int = 20
    ) -> list[VideoEntry]:
        feed_url = channel.feed_url or channel.handle
        feed = feedparser.parse(await self._fetch_text(feed_url))
        entries: list[VideoEntry] = []
        for item in feed.entries[:limit]:
            published = item.get("published_parsed") or item.get("updated_parsed")
            if published:
                published_at = datetime(*published[:6], tzinfo=timezone.utc)
            else:
                published_at = datetime.now(timezone.utc)
            link = item.get("link") or item.get("id") or ""
            thumb = None
            if item.get("media_thumbnail"):
                thumb = item.media_thumbnail[0].get("url")
            elif item.get("enclosures"):
                enc = item.enclosures[0]
                if enc.get("type", "").startswith("image"):
                    thumb = enc.get("href")
            entries.append(
                VideoEntry(
                    video_id=link or item.get("title", "")[:64],
                    title=item.get("title") or "",
                    description=item.get("summary"),
                    published_at=published_at,
                    updated_at=None,
                    thumbnail_url=thumb,
                    tags=[],
                )
            )
        return entries

    async def fetch_comments(
        self, video_id: str, window, limit: int = 100
    ) -> FetchedComments:
        raise NotImplementedError("RSS adapter does not support comments")
