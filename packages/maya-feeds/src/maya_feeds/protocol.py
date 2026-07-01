"""Shared adapter protocol for any platform feed source."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Protocol

from maya_contracts import CommentWindow, Platform


@dataclass(frozen=True)
class ChannelMetadata:
    platform: Platform
    platform_id: str
    handle: str
    display_name: str
    description: Optional[str] = None
    subscriber_count: Optional[int] = None
    video_count: Optional[int] = None
    view_count: Optional[int] = None
    joined_at: Optional[datetime] = None
    feed_url: Optional[str] = None
    profile_links: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class VideoEntry:
    video_id: str
    title: str
    description: Optional[str]
    published_at: datetime
    updated_at: Optional[datetime]
    thumbnail_url: Optional[str]
    duration_seconds: Optional[int] = None
    is_short: bool = False
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CommentRecord:
    platform_comment_id: str
    author_handle: Optional[str]
    author_channel_id: Optional[str]
    text: str
    like_count: int
    published_at: datetime
    reply_count: int
    is_creator_reply: bool


@dataclass(frozen=True)
class FetchedComments:
    video_id: str
    window: CommentWindow
    fetched_at: datetime
    total_count: int
    comments: list[CommentRecord]


class FeedAdapter(Protocol):
    """Each platform implements this minimal surface."""

    platform: Platform

    async def resolve_channel(self, handle: str) -> ChannelMetadata: ...

    async def list_recent_videos(
        self, channel: ChannelMetadata, limit: int = 20
    ) -> list[VideoEntry]: ...

    async def fetch_comments(
        self, video_id: str, window: CommentWindow, limit: int = 100
    ) -> FetchedComments: ...
