"""GitHub release Atom feed adapter."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

import feedparser
import httpx
from maya_contracts import CommentWindow, Platform

from maya_feeds.github_api import extract_tag_from_release_url, parse_repo_slug
from maya_feeds.protocol import ChannelMetadata, FetchedComments, VideoEntry

_RELEASES_ATOM = "https://github.com/{owner}/{repo}/releases.atom"
_TAG_FROM_TITLE = re.compile(r"^v?\d+\.\d+")


class GitHubReleasesAdapter:
    platform = Platform.GITHUB

    def __init__(self, http: Optional[httpx.AsyncClient] = None) -> None:
        self._http = http or httpx.AsyncClient(timeout=20.0, follow_redirects=True)

    async def _fetch_text(self, url: str) -> str:
        resp = await self._http.get(
            url, headers={"User-Agent": "maya-feeds/1.0 (GitHub Releases)"}
        )
        resp.raise_for_status()
        return resp.text

    async def resolve_channel(self, handle: str) -> ChannelMetadata:
        owner, repo = parse_repo_slug(handle)
        slug = f"{owner}/{repo}"
        feed_url = _RELEASES_ATOM.format(owner=owner, repo=repo)
        feed = feedparser.parse(await self._fetch_text(feed_url))
        display_name = (
            feed.feed.get("title") if feed and feed.feed else f"{repo} releases"
        ) or f"{repo} releases"
        return ChannelMetadata(
            platform=Platform.GITHUB,
            platform_id=slug,
            handle=slug,
            display_name=display_name,
            feed_url=feed_url,
            profile_links=[{"url": f"https://github.com/{slug}"}],
        )

    async def list_recent_videos(
        self, channel: ChannelMetadata, limit: int = 20
    ) -> list[VideoEntry]:
        feed_url = channel.feed_url or _RELEASES_ATOM.format(
            owner=channel.platform_id.split("/")[0],
            repo=channel.platform_id.split("/")[1],
        )
        feed = feedparser.parse(await self._fetch_text(feed_url))
        entries: list[VideoEntry] = []
        for item in feed.entries[:limit]:
            link = item.get("link") or item.get("id") or ""
            title = item.get("title") or ""
            tag = extract_tag_from_release_url(link)
            if not tag or tag == link:
                match = _TAG_FROM_TITLE.search(title)
                tag = match.group(0) if match else title[:64]
            published = item.get("published_parsed") or item.get("updated_parsed")
            if published:
                published_at = datetime(*published[:6], tzinfo=timezone.utc)
            else:
                published_at = datetime.now(timezone.utc)
            updated = item.get("updated_parsed")
            updated_at = (
                datetime(*updated[:6], tzinfo=timezone.utc) if updated else None
            )
            entries.append(
                VideoEntry(
                    video_id=tag,
                    title=title,
                    description=item.get("summary") or item.get("content"),
                    published_at=published_at,
                    updated_at=updated_at,
                    thumbnail_url=None,
                    tags=[tag],
                )
            )
        return entries

    async def fetch_comments(
        self, video_id: str, window: CommentWindow, limit: int = 100
    ) -> FetchedComments:
        raise NotImplementedError("GitHub releases adapter does not support comments")
