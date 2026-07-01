"""Parse YouTube video description into intel items."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from maya_contracts import (
    AnalysisStatus,
    IntelItem,
    IntelItemKind,
    NotificationKind,
)
from maya_db import (
    Channel as ChannelDB,
    IntelItem as IntelItemDB,
    Notification as NotificationDB,
    Video as VideoDB,
    VideoIntelLink as VideoIntelLinkDB,
    get_async_session,
)
from maya_feeds.youtube_intel import extract_intel_items
from prefect import flow, get_run_logger, task
from sqlalchemy import select


@task
async def _run_video_intel(video_uuid: str) -> bool:
    logger = get_run_logger()
    vid = UUID(video_uuid)
    async for session in get_async_session():
        video = await session.get(VideoDB, vid)
        if video is None:
            logger.warning("video %s not found", video_uuid)
            return False
        if not video.description:
            video.analysis_status = AnalysisStatus.SKIPPED.value
            await session.commit()
            return False

        channel = await session.get(ChannelDB, video.channel_id)
        if channel is None:
            return False

        video.analysis_status = AnalysisStatus.RUNNING.value
        await session.flush()

        try:
            raw_items = extract_intel_items(video.description)
            now = datetime.now(timezone.utc)
            intel_models: list[IntelItem] = []

            for pos, raw in enumerate(raw_items):
                if not raw.get("canonical_url"):
                    continue
                canonical = raw["canonical_url"]
                kind = raw.get("kind", IntelItemKind.UNKNOWN)
                if isinstance(kind, IntelItemKind):
                    kind_str = kind.value
                else:
                    kind_str = str(kind)

                existing_item = (
                    await session.execute(
                        select(IntelItemDB).where(
                            IntelItemDB.canonical_url == canonical
                        )
                    )
                ).scalar_one_or_none()

                if existing_item is None:
                    item_row = IntelItemDB(
                        canonical_url=canonical,
                        label=raw["label"],
                        kind=kind_str,
                        first_seen_at=now,
                        metadata_={"url": raw.get("url") or canonical},
                    )
                    session.add(item_row)
                    await session.flush()
                else:
                    item_row = existing_item

                link_exists = (
                    await session.execute(
                        select(VideoIntelLinkDB).where(
                            VideoIntelLinkDB.video_id == video.id,
                            VideoIntelLinkDB.intel_item_id == item_row.id,
                        )
                    )
                ).scalar_one_or_none()
                if link_exists is None:
                    session.add(
                        VideoIntelLinkDB(
                            video_id=video.id,
                            intel_item_id=item_row.id,
                            timestamp_seconds=raw.get("timestamp_seconds"),
                            position=pos,
                        )
                    )

                intel_models.append(
                    IntelItem(
                        id=str(item_row.id),
                        label=item_row.label,
                        url=raw.get("url") or canonical,
                        canonical_url=canonical,
                        kind=IntelItemKind(item_row.kind),
                        timestamp_seconds=raw.get("timestamp_seconds"),
                        metadata=item_row.metadata_ or {},
                        first_seen_at=item_row.first_seen_at,
                    )
                )

            video.analysis_status = AnalysisStatus.DONE.value
            session.add(
                NotificationDB(
                    kind=NotificationKind.INTEL_EXTRACTED.value,
                    channel_id=channel.id,
                    video_id=video.id,
                    title=f"Intel extracted: {video.title[:80]}",
                    body=f"{len(intel_models)} items",
                    link=f"/api/intel/videos/{video.id}/intel",
                    read=False,
                )
            )
            await session.commit()
            logger.info(
                "extracted %d intel items from video %s", len(intel_models), video_uuid
            )
            return True
        except Exception as exc:
            logger.exception("video intel parse failed for %s: %s", video_uuid, exc)
            video.analysis_status = AnalysisStatus.FAILED.value
            await session.commit()
            return False
    return False


@flow(name="parse-video-intel")
async def parse_video_intel(video_uuid: str) -> bool:
    """Parse chapters and URLs from a YouTube video description."""
    return await _run_video_intel(video_uuid)
