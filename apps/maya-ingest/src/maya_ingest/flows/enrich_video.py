"""Pull duration/likes/tags from the platform API onto an existing Video row."""

from __future__ import annotations

from maya_contracts import Platform
from maya_db import Channel as ChannelDB, Video as VideoDB, get_async_session
from maya_feeds import YouTubeAdapter
from prefect import flow, get_run_logger


@flow(name="enrich-video")
async def enrich_video(video_id: str) -> bool:
    logger = get_run_logger()
    async for session in get_async_session():
        video = await session.get(VideoDB, video_id)
        if video is None:
            return False
        channel = await session.get(ChannelDB, video.channel_id)
        if Platform(channel.platform) != Platform.YOUTUBE:
            return False
        adapter = YouTubeAdapter()
        extra = await adapter.enrich_video(video.video_id)
        if not extra:
            return False
        video.duration_seconds = extra.get("duration_seconds")
        video.is_short = bool(extra.get("is_short"))
        if extra.get("view_count") is not None:
            video.view_count = extra["view_count"]
        if extra.get("like_count") is not None:
            video.like_count = extra["like_count"]
        if extra.get("comment_count") is not None:
            video.comment_count = extra["comment_count"]
        await session.commit()
        logger.info("enriched %s", video.video_id)
    return True
