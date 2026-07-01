"""Per-subscription feed poll: read Atom, upsert videos, fan out enrichment."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from maya_contracts import AnalysisStatus, FetchCadence, NotificationKind, Platform
from maya_db import (
    Channel as ChannelDB,
    Follow as FollowDB,
    Notification as NotificationDB,
    PersonChannel as PersonChannelDB,
    Subscription as SubscriptionDB,
    Video as VideoDB,
    get_async_session,
)
from maya_feeds import get_adapter
from prefect import flow, get_run_logger, task
from sqlalchemy import or_, select
from sqlalchemy.exc import ProgrammingError

_CADENCE_TO_DELTA = {
    FetchCadence.HOURLY: timedelta(hours=1),
    FetchCadence.DAILY: timedelta(days=1),
    FetchCadence.WEEKLY: timedelta(days=7),
    FetchCadence.MANUAL: timedelta(days=365 * 10),
}


def _default_analysis_config(platform: str) -> Optional[dict[str, Any]]:
    if platform == Platform.GITHUB.value:
        return {"kind": "github_releases", "auto_analyze": True, "llm_enabled": True}
    if platform == Platform.YOUTUBE.value:
        return {"kind": "youtube_intel", "auto_analyze": True, "llm_enabled": False}
    return None


def _should_auto_analyze(sub: SubscriptionDB, platform: str) -> bool:
    cfg = sub.analysis_config or _default_analysis_config(platform)
    if cfg is None:
        return False
    return bool(cfg.get("auto_analyze", False))


@flow(name="poll-subscriptions")
async def poll_subscriptions() -> int:
    """Tick: poll every subscription whose cadence has elapsed."""
    logger = get_run_logger()
    polled = 0
    async for session in get_async_session():
        stmt = (
            select(SubscriptionDB, ChannelDB)
            .join(ChannelDB, SubscriptionDB.channel_id == ChannelDB.id)
            .where(SubscriptionDB.enabled.is_(True))
        )
        rows = (await session.execute(stmt)).all()
        now = datetime.now(timezone.utc)
        for sub, channel in rows:
            cadence = FetchCadence(sub.cadence)
            delta = _CADENCE_TO_DELTA[cadence]
            if channel.last_fetched_at and channel.last_fetched_at + delta > now:
                continue
            polled += 1
            await _poll_one(session, channel, sub)
        await session.commit()
    logger.info("polled %d subscriptions", polled)
    return polled


@task
async def _poll_one(
    session, channel: ChannelDB, sub: SubscriptionDB
) -> None:
    # Snapshot the seed flag BEFORE we mutate last_fetched_at — the first
    # poll for a channel is a silent backfill of the Atom-feed window so
    # that the user doesn't get a flood of ~15 "new video" notifications
    # right after subscribing.
    seed_run = channel.last_fetched_at is None

    adapter = get_adapter(Platform(channel.platform))
    metadata = await adapter.resolve_channel(channel.handle)
    entries = await adapter.list_recent_videos(metadata, limit=20)
    existing_ids = set(
        (
            await session.execute(
                select(VideoDB.video_id).where(VideoDB.channel_id == channel.id)
            )
        )
        .scalars()
        .all()
    )

    emit_notifications = not seed_run
    notify_operators: list[str] = []
    if emit_notifications:
        notify_operators = await _notify_operators(session, channel.id)
    auto_analyze = _should_auto_analyze(sub, channel.platform)
    new_video_ids: list[str] = []

    for entry in entries:
        if entry.video_id in existing_ids:
            continue
        analysis_status = None
        if auto_analyze:
            analysis_status = (
                AnalysisStatus.SKIPPED.value if seed_run else AnalysisStatus.PENDING.value
            )
        video = VideoDB(
            channel_id=channel.id,
            video_id=entry.video_id,
            title=entry.title,
            description=entry.description,
            published_at=entry.published_at,
            feed_updated_at=entry.updated_at,
            thumbnail_url=entry.thumbnail_url,
            is_short=entry.is_short,
            source_phase="live",
            analysis_status=analysis_status,
        )
        session.add(video)
        await session.flush()
        if not seed_run and auto_analyze:
            new_video_ids.append(str(video.id))
        if not notify_operators:
            continue
        for operator_id in notify_operators:
            session.add(
                NotificationDB(
                    kind=NotificationKind.NEW_VIDEO.value,
                    operator_id=operator_id,
                    channel_id=channel.id,
                    video_id=video.id,
                    title=entry.title,
                    body=channel.display_name,
                    link=f"/feeds/videos/{video.id}",
                    read=False,
                )
            )
    channel.last_fetched_at = datetime.now(timezone.utc)

    if new_video_ids:
        await _fan_out_analysis(channel.platform, new_video_ids)


@task
async def _fan_out_analysis(platform: str, video_ids: list[str]) -> None:
    if platform == Platform.GITHUB.value:
        from maya_ingest.flows.analyze_release import _run_release_analysis

        for vid in video_ids:
            _run_release_analysis.submit(vid)
    elif platform == Platform.YOUTUBE.value:
        from maya_ingest.flows.parse_video_intel import _run_video_intel

        for vid in video_ids:
            _run_video_intel.submit(vid)


async def _notify_operators(session, channel_id: UUID) -> list[str]:
    """Operators with active follow covering this channel and notify_homepage on."""
    person_ids_subq = select(PersonChannelDB.person_id).where(
        PersonChannelDB.channel_id == channel_id
    )
    stmt = select(FollowDB.operator_id).where(
        FollowDB.muted.is_(False),
        FollowDB.deleted_at.is_(None),
        FollowDB.notify_homepage.is_(True),
        or_(
            (FollowDB.subject_type == "CHANNEL") & (FollowDB.subject_id == channel_id),
            (FollowDB.subject_type == "PERSON")
            & (FollowDB.subject_id.in_(person_ids_subq)),
        ),
    )
    try:
        rows = (await session.execute(stmt)).scalars().all()
    except ProgrammingError:
        return ["local"]
    return list(dict.fromkeys(rows)) if rows else []


async def _has_unmuted_follow(session, channel_id: UUID) -> bool:
    """True if some operator has an active (non-muted, non-deleted) Follow
    that covers this channel — either directly (subject_type='CHANNEL',
    subject_id=channel_id) or transitively via a Person that's attached
    to this channel through ``feed_person_channels``.

    Falls back to True if the feed_follows table isn't present (legacy
    deployment that never ran the follow migration) so the prior
    "emit-for-every-subscription" behavior is preserved.
    """
    person_ids_subq = select(PersonChannelDB.person_id).where(
        PersonChannelDB.channel_id == channel_id
    )
    stmt = (
        select(FollowDB.id)
        .where(FollowDB.muted.is_(False))
        .where(FollowDB.deleted_at.is_(None))
        .where(
            or_(
                (FollowDB.subject_type == "CHANNEL")
                & (FollowDB.subject_id == channel_id),
                (FollowDB.subject_type == "PERSON")
                & (FollowDB.subject_id.in_(person_ids_subq)),
            )
        )
        .limit(1)
    )
    try:
        result = (await session.execute(stmt)).scalar_one_or_none()
    except ProgrammingError:
        return True
    return result is not None
