"""Instagram adapter stub.

Instagram does not publish open RSS/Atom feeds. Production deployments wire
this against an authenticated source (oEmbed + Graph API, or a third-party
mirror service). Public-boundary repo ships the protocol shape only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from maya_contracts import CommentWindow, Platform

from maya_feeds.protocol import (
    ChannelMetadata,
    FetchedComments,
    VideoEntry,
)


class InstagramAdapter:
    platform = Platform.INSTAGRAM

    def __init__(self, access_token: Optional[str] = None) -> None:
        self._access_token = access_token

    async def resolve_channel(self, handle: str) -> ChannelMetadata:
        normalized = handle.lstrip("@")
        return ChannelMetadata(
            platform=Platform.INSTAGRAM,
            platform_id=normalized,
            handle=f"@{normalized}",
            display_name=normalized,
        )

    async def list_recent_videos(
        self, channel: ChannelMetadata, limit: int = 20
    ) -> list[VideoEntry]:
        return []

    async def fetch_comments(
        self, video_id: str, window: CommentWindow, limit: int = 100
    ) -> FetchedComments:
        return FetchedComments(
            video_id=video_id,
            window=window,
            fetched_at=datetime.now(timezone.utc),
            total_count=0,
            comments=[],
        )
