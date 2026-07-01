"""Feed intel API: release analyses, extracted items, trends."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from maya_contracts import (
    AnalysisSummary,
    FileChange,
    IntelItem,
    IntelItemKind,
    PaginatedResponse,
    ReleaseAnalysis,
    TrendCluster,
    VideoIntel,
    Chapter,
)
from maya_db import (
    Channel as ChannelDB,
    FeedAnalysis as FeedAnalysisDB,
    IntelItem as IntelItemDB,
    Video as VideoDB,
    VideoIntelLink as VideoIntelLinkDB,
    get_async_session,
)
from sqlalchemy import func, select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/intel", tags=["intel"])


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid uuid") from exc


def _analysis_to_response(row: FeedAnalysisDB, channel: ChannelDB) -> ReleaseAnalysis:
    payload = row.payload or {}
    analysis_raw = payload.get("analysis")
    analysis = AnalysisSummary.model_validate(analysis_raw) if analysis_raw else None
    file_changes = [
        FileChange.model_validate(f) for f in payload.get("file_changes", [])
    ]
    return ReleaseAnalysis(
        id=str(row.id),
        repo=channel.handle,
        from_tag=row.from_tag,
        to_tag=row.to_tag,
        release_url=row.release_url or payload.get("release_url", ""),
        release_notes=payload.get("release_notes"),
        file_changes=file_changes,
        analysis=analysis,
        generated_at=row.generated_at,
    )


def _item_to_response(item: IntelItemDB) -> IntelItem:
    meta = item.metadata_ or {}
    return IntelItem(
        id=str(item.id),
        label=item.label,
        url=meta.get("url", item.canonical_url),
        canonical_url=item.canonical_url,
        kind=IntelItemKind(item.kind),
        metadata=meta,
        first_seen_at=item.first_seen_at,
    )


@router.get("/releases", response_model=PaginatedResponse[ReleaseAnalysis])
async def list_releases(
    repo: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    session: "AsyncSession" = Depends(get_async_session),
):
    stmt = (
        select(FeedAnalysisDB, ChannelDB)
        .join(ChannelDB, FeedAnalysisDB.channel_id == ChannelDB.id)
        .order_by(FeedAnalysisDB.generated_at.desc())
    )
    if repo:
        stmt = stmt.where(ChannelDB.handle == repo)
    total = len((await session.execute(stmt)).all())
    rows = (await session.execute(stmt.limit(limit).offset(offset))).all()
    items = [_analysis_to_response(a, c) for a, c in rows]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/releases/{analysis_id}", response_model=ReleaseAnalysis)
async def get_release(
    analysis_id: str,
    session: "AsyncSession" = Depends(get_async_session),
):
    row = await session.get(FeedAnalysisDB, _uuid(analysis_id))
    if row is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    channel = await session.get(ChannelDB, row.channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="channel not found")
    return _analysis_to_response(row, channel)


@router.get("/items", response_model=PaginatedResponse[IntelItem])
async def list_items(
    kind: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    session: "AsyncSession" = Depends(get_async_session),
):
    stmt = select(IntelItemDB).order_by(IntelItemDB.first_seen_at.desc())
    if kind:
        stmt = stmt.where(IntelItemDB.kind == kind)
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid since timestamp") from exc
        stmt = stmt.where(IntelItemDB.first_seen_at >= since_dt)
    total = len((await session.execute(stmt)).scalars().all())
    rows = (await session.execute(stmt.limit(limit).offset(offset))).scalars().all()
    items = [_item_to_response(r) for r in rows]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/items/{item_id}", response_model=IntelItem)
async def get_item(
    item_id: str,
    session: "AsyncSession" = Depends(get_async_session),
):
    row = await session.get(IntelItemDB, _uuid(item_id))
    if row is None:
        raise HTTPException(status_code=404, detail="item not found")
    return _item_to_response(row)


@router.get("/trends", response_model=list[TrendCluster])
async def list_trends(
    window: str = "7d",
    limit: int = 20,
    session: "AsyncSession" = Depends(get_async_session),
):
    days = 7
    if window.endswith("d"):
        try:
            days = int(window[:-1])
        except ValueError:
            days = 7
    since = datetime.now(timezone.utc) - timedelta(days=days)

    stmt = (
        select(
            IntelItemDB.canonical_url,
            IntelItemDB.label,
            IntelItemDB.kind,
            func.count(VideoIntelLinkDB.id).label("item_count"),
            func.count(func.distinct(VideoDB.channel_id)).label("channel_count"),
            func.min(VideoDB.published_at).label("first_seen"),
            func.max(VideoDB.published_at).label("last_seen"),
        )
        .join(VideoIntelLinkDB, VideoIntelLinkDB.intel_item_id == IntelItemDB.id)
        .join(VideoDB, VideoDB.id == VideoIntelLinkDB.video_id)
        .where(VideoDB.published_at >= since)
        .group_by(IntelItemDB.id, IntelItemDB.canonical_url, IntelItemDB.label, IntelItemDB.kind)
        .order_by(func.count(func.distinct(VideoDB.channel_id)).desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    clusters: list[TrendCluster] = []
    for row in rows:
        channel_stmt = (
            select(ChannelDB.display_name)
            .join(VideoDB, VideoDB.channel_id == ChannelDB.id)
            .join(VideoIntelLinkDB, VideoIntelLinkDB.video_id == VideoDB.id)
            .join(IntelItemDB, IntelItemDB.id == VideoIntelLinkDB.intel_item_id)
            .where(IntelItemDB.canonical_url == row.canonical_url)
            .where(VideoDB.published_at >= since)
            .distinct()
        )
        channels = list((await session.execute(channel_stmt)).scalars().all())
        clusters.append(
            TrendCluster(
                canonical_url=row.canonical_url,
                label=row.label,
                kind=IntelItemKind(row.kind),
                item_count=row.item_count,
                channel_count=row.channel_count,
                channels=channels,
                first_seen=row.first_seen,
                last_seen=row.last_seen,
            )
        )
    return clusters


@router.get("/videos/{video_id}/intel", response_model=VideoIntel)
async def get_video_intel(
    video_id: str,
    session: "AsyncSession" = Depends(get_async_session),
):
    vid = _uuid(video_id)
    video = await session.get(VideoDB, vid)
    if video is None:
        raise HTTPException(status_code=404, detail="video not found")

    link_stmt = (
        select(VideoIntelLinkDB, IntelItemDB)
        .join(IntelItemDB, IntelItemDB.id == VideoIntelLinkDB.intel_item_id)
        .where(VideoIntelLinkDB.video_id == vid)
        .order_by(VideoIntelLinkDB.position)
    )
    links = (await session.execute(link_stmt)).all()
    items: list[IntelItem] = []
    chapters: list[Chapter] = []
    for link, item in links:
        items.append(
            IntelItem(
                id=str(item.id),
                label=item.label,
                url=(item.metadata_ or {}).get("url", item.canonical_url),
                canonical_url=item.canonical_url,
                kind=IntelItemKind(item.kind),
                timestamp_seconds=link.timestamp_seconds,
                metadata=item.metadata_ or {},
                first_seen_at=item.first_seen_at,
            )
        )
        if link.timestamp_seconds is not None:
            mins, secs = divmod(link.timestamp_seconds, 60)
            chapters.append(
                Chapter(
                    timestamp=f"{mins}:{secs:02d}",
                    label=item.label,
                    timestamp_seconds=link.timestamp_seconds,
                )
            )

    return VideoIntel(
        video_id=video.video_id,
        channel_id=str(video.channel_id),
        title=video.title,
        chapters=chapters,
        items=items,
        generated_at=video.updated_at or video.created_at,
    )
