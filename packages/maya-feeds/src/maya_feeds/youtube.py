"""YouTube adapter: Atom feed for free polling + Data API v3 for enrichment."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Optional

import feedparser
import httpx
from maya_contracts import CommentWindow, Platform

from maya_feeds.protocol import (
    ChannelMetadata,
    CommentRecord,
    FetchedComments,
    VideoEntry,
)

_ATOM_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
_HANDLE_PAGE = "https://www.youtube.com/{handle}"
_CHANNEL_ID_RE = re.compile(r'"channelId":"(UC[\w-]{20,})"')
_ABOUT_BIO_RE = re.compile(r'"description":\{"simpleText":"([^"]+)"\}')
_LINK_RE = re.compile(r'https?://[^\s"\']+')


class YouTubeAdapter:
    platform = Platform.YOUTUBE

    def __init__(
        self,
        api_key: Optional[str] = None,
        http: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._api_key = api_key or os.getenv("YOUTUBE_API_KEY")
        self._http = http or httpx.AsyncClient(timeout=20.0)

    async def resolve_channel(self, handle: str) -> ChannelMetadata:
        normalized = handle if handle.startswith("@") else f"@{handle.lstrip('@')}"
        resp = await self._http.get(_HANDLE_PAGE.format(handle=normalized))
        resp.raise_for_status()
        body = resp.text
        match = _CHANNEL_ID_RE.search(body)
        if not match:
            raise ValueError(f"could not resolve YouTube channel id for {handle}")
        channel_id = match.group(1)
        bio_match = _ABOUT_BIO_RE.search(body)
        description = bio_match.group(1).encode().decode("unicode_escape") if bio_match else None
        profile_links = []
        if description:
            for url in _LINK_RE.findall(description):
                profile_links.append({"url": url})

        feed_url = _ATOM_FEED.format(channel_id=channel_id)
        feed = feedparser.parse(await self._fetch_text(feed_url))
        display_name = (
            feed.feed.get("title") if feed and feed.feed else normalized
        ) or normalized

        return ChannelMetadata(
            platform=Platform.YOUTUBE,
            platform_id=channel_id,
            handle=normalized,
            display_name=display_name,
            description=description,
            feed_url=feed_url,
            profile_links=profile_links,
        )

    async def list_recent_videos(
        self, channel: ChannelMetadata, limit: int = 20
    ) -> list[VideoEntry]:
        feed_url = channel.feed_url or _ATOM_FEED.format(channel_id=channel.platform_id)
        feed = feedparser.parse(await self._fetch_text(feed_url))
        out: list[VideoEntry] = []
        for entry in feed.entries[:limit]:
            video_id = entry.get("yt_videoid") or entry.get("id", "").rsplit(":", 1)[-1]
            published = _parse_dt(entry.get("published"))
            updated = _parse_dt(entry.get("updated"))
            media_thumb = (
                entry.get("media_thumbnail", [{}])[0] if entry.get("media_thumbnail") else {}
            )
            description = entry.get("summary")
            out.append(
                VideoEntry(
                    video_id=video_id,
                    title=entry.get("title", ""),
                    description=description,
                    published_at=published,
                    updated_at=updated,
                    thumbnail_url=media_thumb.get("url"),
                    is_short=False,  # Atom feed does not expose this; enrich_video fills it in.
                )
            )
        return out

    async def fetch_comments(
        self, video_id: str, window: CommentWindow, limit: int = 100
    ) -> FetchedComments:
        if not self._api_key:
            return FetchedComments(
                video_id=video_id,
                window=window,
                fetched_at=datetime.now(timezone.utc),
                total_count=0,
                comments=[],
            )
        url = "https://www.googleapis.com/youtube/v3/commentThreads"
        params = {
            "part": "snippet",
            "videoId": video_id,
            "order": "relevance",
            "maxResults": min(limit, 100),
            "key": self._api_key,
        }
        resp = await self._http.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        comments: list[CommentRecord] = []
        for item in data.get("items", []):
            snip = item["snippet"]["topLevelComment"]["snippet"]
            comments.append(
                CommentRecord(
                    platform_comment_id=item["snippet"]["topLevelComment"]["id"],
                    author_handle=snip.get("authorDisplayName"),
                    author_channel_id=(snip.get("authorChannelId") or {}).get("value"),
                    text=snip.get("textOriginal", ""),
                    like_count=int(snip.get("likeCount", 0)),
                    published_at=_parse_dt(snip.get("publishedAt")) or datetime.now(timezone.utc),
                    reply_count=int(item["snippet"].get("totalReplyCount", 0)),
                    is_creator_reply=False,
                )
            )
        return FetchedComments(
            video_id=video_id,
            window=window,
            fetched_at=datetime.now(timezone.utc),
            total_count=int(data.get("pageInfo", {}).get("totalResults", len(comments))),
            comments=comments,
        )

    async def enrich_video(self, video_id: str) -> dict:
        """Fetch duration/likes/tags from Data API. Returns empty dict if no API key."""
        if not self._api_key:
            return {}
        url = "https://www.googleapis.com/youtube/v3/videos"
        params = {
            "part": "snippet,contentDetails,statistics",
            "id": video_id,
            "key": self._api_key,
        }
        resp = await self._http.get(url, params=params)
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            return {}
        item = items[0]
        snip = item.get("snippet", {})
        cd = item.get("contentDetails", {})
        stats = item.get("statistics", {})
        duration = _iso_duration_to_seconds(cd.get("duration"))
        return {
            "duration_seconds": duration,
            "is_short": (duration is not None and duration <= 60),
            "tags": snip.get("tags", []),
            "view_count": int(stats.get("viewCount", 0)) if "viewCount" in stats else None,
            "like_count": int(stats.get("likeCount", 0)) if "likeCount" in stats else None,
            "comment_count": int(stats.get("commentCount", 0)) if "commentCount" in stats else None,
        }

    async def _fetch_text(self, url: str) -> str:
        resp = await self._http.get(url)
        resp.raise_for_status()
        return resp.text


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


_DUR_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def _iso_duration_to_seconds(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    m = _DUR_RE.fullmatch(value)
    if not m:
        return None
    h, mi, s = m.groups()
    return int(h or 0) * 3600 + int(mi or 0) * 60 + int(s or 0)
