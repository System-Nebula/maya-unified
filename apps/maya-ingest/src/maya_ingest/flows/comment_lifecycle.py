"""Time-windowed comment fetching: T24H / T72H / T1W."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from maya_contracts import CommentWindow, Platform
from maya_db import (
    Channel as ChannelDB,
    Comment as CommentDB,
    CommentSnapshot as SnapshotDB,
    Video as VideoDB,
    get_async_session,
)
from maya_feeds import get_adapter
from prefect import flow, get_run_logger
from sqlalchemy import select

FETCH_SCHEDULE: list[tuple[timedelta, CommentWindow]] = [
    (timedelta(hours=24), CommentWindow.T24H),
    (timedelta(hours=72), CommentWindow.T72H),
    (timedelta(days=7), CommentWindow.T1W),
]


@flow(name="video-comment-lifecycle")
async def video_comment_lifecycle(video_id: str) -> int:
    """Run all due fetch-window snapshots for a single video.

    Idempotent: skips windows whose snapshot already exists.
    """
    logger = get_run_logger()
    snapshots = 0
    async for session in get_async_session():
        video = await session.get(VideoDB, video_id)
        if video is None:
            logger.warning("no such video %s", video_id)
            return 0
        channel = await session.get(ChannelDB, video.channel_id)
        adapter = get_adapter(Platform(channel.platform))
        now = datetime.now(timezone.utc)

        existing_windows = {
            row[0]
            for row in (
                await session.execute(
                    select(SnapshotDB.fetch_window).where(SnapshotDB.video_id == video.id)
                )
            ).all()
        }

        for offset, window in FETCH_SCHEDULE:
            if window.value in existing_windows:
                continue
            if video.published_at + offset > now:
                continue
            fetched = await adapter.fetch_comments(video.video_id, window)
            snapshot = SnapshotDB(
                video_id=video.id,
                fetched_at=fetched.fetched_at,
                fetch_window=window.value,
                total_count=fetched.total_count,
            )
            session.add(snapshot)
            await session.flush()
            for comment in fetched.comments:
                session.add(
                    CommentDB(
                        snapshot_id=snapshot.id,
                        platform_comment_id=comment.platform_comment_id,
                        author_handle=comment.author_handle,
                        author_channel_id=comment.author_channel_id,
                        text=comment.text,
                        like_count=comment.like_count,
                        published_at=comment.published_at,
                        reply_count=comment.reply_count,
                        is_creator_reply=comment.is_creator_reply,
                    )
                )
            snapshots += 1
        await session.commit()
    return snapshots
