"""Platform feed adapters."""

from maya_feeds.protocol import (
    ChannelMetadata,
    CommentRecord,
    FeedAdapter,
    FetchedComments,
    VideoEntry,
)
from maya_feeds.github import GitHubReleasesAdapter
from maya_feeds.youtube import YouTubeAdapter
from maya_feeds.instagram import InstagramAdapter
from maya_feeds.tiktok import TikTokAdapter
from maya_feeds.registry import get_adapter

__all__ = [
    "ChannelMetadata",
    "CommentRecord",
    "FeedAdapter",
    "FetchedComments",
    "VideoEntry",
    "YouTubeAdapter",
    "GitHubReleasesAdapter",
    "InstagramAdapter",
    "TikTokAdapter",
    "get_adapter",
]
