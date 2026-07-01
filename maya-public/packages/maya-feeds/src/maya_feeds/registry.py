"""Platform → adapter lookup."""

from __future__ import annotations

from maya_contracts import Platform

from maya_feeds.github import GitHubReleasesAdapter
from maya_feeds.instagram import InstagramAdapter
from maya_feeds.protocol import FeedAdapter
from maya_feeds.rss import RssAdapter
from maya_feeds.tiktok import TikTokAdapter
from maya_feeds.youtube import YouTubeAdapter


def get_adapter(platform: Platform) -> FeedAdapter:
    if platform == Platform.YOUTUBE:
        return YouTubeAdapter()
    if platform == Platform.INSTAGRAM:
        return InstagramAdapter()
    if platform == Platform.TIKTOK:
        return TikTokAdapter()
    if platform == Platform.RSS:
        return RssAdapter()
    if platform == Platform.GITHUB:
        return GitHubReleasesAdapter()
    raise ValueError(f"unsupported platform: {platform}")
