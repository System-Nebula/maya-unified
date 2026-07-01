"""Creator-intel feed endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from maya_contracts import (
    AnalysisStatus,
    Channel,
    Comment,
    CommentSnapshot,
    CrossPlatformMatch,
    FetchCadence,
    MatchSignal,
    MergePersonsRequest,
    PaginatedResponse,
    Person,
    PersonChannelLink,
    Platform,
    SubscribeRequest,
    SubscribeResponse,
    Video,
    VideoSimilarity,
)
from maya_db import (
    Channel as ChannelDB,
    Comment as CommentDB,
    CommentSnapshot as SnapshotDB,
    Person as PersonDB,
    PersonChannel as PersonChannelDB,
    Subscription as SubscriptionDB,
    Video as VideoDB,
    VideoSimilarity as SimilarityDB,
    get_async_session,
)
from maya_feeds import get_adapter
from sqlalchemy import and_, or_, select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/feeds", tags=["feeds"])


def _channel_to_response(c: ChannelDB) -> Channel:
    return Channel(
        id=str(c.id),
        platform=Platform(c.platform),
        platform_id=c.platform_id,
        handle=c.handle,
        display_name=c.display_name,
        description=c.description,
        subscriber_count=c.subscriber_count,
        video_count=c.video_count,
        view_count=c.view_count,
        joined_at=c.joined_at,
        feed_url=c.feed_url,
        cadence=FetchCadence(c.cadence),
        last_fetched_at=c.last_fetched_at,
        identity_confidence=c.identity_confidence,
    )


def _video_to_response(v: VideoDB) -> Video:
    return Video(
        id=str(v.id),
        video_id=v.video_id,
        channel_id=str(v.channel_id),
        title=v.title,
        description=v.description,
        published_at=v.published_at,
        updated_at=v.feed_updated_at,
        duration_seconds=v.duration_seconds,
        is_short=v.is_short,
        thumbnail_url=v.thumbnail_url,
        view_count=v.view_count,
        like_count=v.like_count,
        comment_count=v.comment_count,
        has_embedding=v.embedding is not None,
        has_thumbnail_embedding=v.thumbnail_embedding is not None,
        analysis_status=AnalysisStatus(v.analysis_status) if v.analysis_status else None,
    )


def _comment_to_response(c: CommentDB) -> Comment:
    return Comment(
        id=str(c.id),
        platform_comment_id=c.platform_comment_id,
        snapshot_id=str(c.snapshot_id),
        author_handle=c.author_handle,
        author_channel_id=c.author_channel_id,
        text=c.text,
        like_count=c.like_count,
        published_at=c.published_at,
        reply_count=c.reply_count,
        is_creator_reply=c.is_creator_reply,
        sentiment_score=c.sentiment_score,
        has_embedding=c.embedding is not None,
    )


@router.post("/subscribe", response_model=SubscribeResponse)
async def subscribe(
    req: SubscribeRequest,
    session: "AsyncSession" = Depends(get_async_session),
):
    adapter = get_adapter(req.platform)
    metadata = await adapter.resolve_channel(req.handle)

    analysis_config = None
    if req.analysis_config is not None:
        analysis_config = req.analysis_config.model_dump()
    elif req.platform == Platform.GITHUB:
        analysis_config = {
            "kind": "github_releases",
            "auto_analyze": True,
            "llm_enabled": True,
        }
    elif req.platform == Platform.YOUTUBE:
        analysis_config = {
            "kind": "youtube_intel",
            "auto_analyze": True,
            "llm_enabled": False,
        }

    stmt = select(ChannelDB).where(
        and_(
            ChannelDB.platform == req.platform.value,
            ChannelDB.platform_id == metadata.platform_id,
        )
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is None:
        channel = ChannelDB(
            platform=req.platform.value,
            platform_id=metadata.platform_id,
            handle=metadata.handle,
            display_name=metadata.display_name,
            description=metadata.description,
            feed_url=metadata.feed_url,
            cadence=req.cadence.value,
            profile_links=list(metadata.profile_links),
        )
        session.add(channel)
        await session.flush()
    else:
        channel = existing
        channel.handle = metadata.handle
        channel.display_name = metadata.display_name
        if metadata.description:
            channel.description = metadata.description
        channel.cadence = req.cadence.value

    sub_stmt = select(SubscriptionDB).where(SubscriptionDB.channel_id == channel.id)
    sub = (await session.execute(sub_stmt)).scalar_one_or_none()
    if sub is None:
        sub = SubscriptionDB(
            channel_id=channel.id,
            cadence=req.cadence.value,
            fetch_comments=req.fetch_comments,
            comment_windows=[w.value for w in req.comment_windows],
            analysis_config=analysis_config,
        )
        session.add(sub)
    else:
        sub.cadence = req.cadence.value
        sub.fetch_comments = req.fetch_comments
        sub.comment_windows = [w.value for w in req.comment_windows]
        if analysis_config is not None:
            sub.analysis_config = analysis_config
        sub.enabled = True

    await session.flush()
    return SubscribeResponse(channel=_channel_to_response(channel))


@router.delete("/subscribe/{channel_id}")
async def unsubscribe(
    channel_id: str,
    session: "AsyncSession" = Depends(get_async_session),
):
    stmt = select(SubscriptionDB).where(SubscriptionDB.channel_id == _uuid(channel_id))
    sub = (await session.execute(stmt)).scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    sub.enabled = False
    await session.flush()
    return {"channel_id": channel_id, "enabled": False}


@router.get("/channels", response_model=PaginatedResponse[Channel])
async def list_channels(
    limit: int = 50,
    offset: int = 0,
    session: "AsyncSession" = Depends(get_async_session),
):
    total = len((await session.execute(select(ChannelDB.id))).scalars().all())
    result = await session.execute(
        select(ChannelDB).order_by(ChannelDB.created_at.desc()).limit(limit).offset(offset)
    )
    items = [_channel_to_response(c) for c in result.scalars().all()]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/channels/{channel_id}/videos", response_model=PaginatedResponse[Video])
async def list_channel_videos(
    channel_id: str,
    limit: int = 50,
    offset: int = 0,
    is_short: Optional[bool] = None,
    session: "AsyncSession" = Depends(get_async_session),
):
    cid = _uuid(channel_id)
    base = select(VideoDB).where(VideoDB.channel_id == cid)
    if is_short is not None:
        base = base.where(VideoDB.is_short == is_short)
    total = len((await session.execute(base)).scalars().all())
    result = await session.execute(
        base.order_by(VideoDB.published_at.desc()).limit(limit).offset(offset)
    )
    items = [_video_to_response(v) for v in result.scalars().all()]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/videos/{video_id}/comments", response_model=PaginatedResponse[Comment])
async def list_video_comments(
    video_id: str,
    window: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    session: "AsyncSession" = Depends(get_async_session),
):
    vid = _uuid(video_id)
    snap_stmt = select(SnapshotDB).where(SnapshotDB.video_id == vid)
    if window:
        snap_stmt = snap_stmt.where(SnapshotDB.fetch_window == window)
    snap_stmt = snap_stmt.order_by(SnapshotDB.fetched_at.desc()).limit(1)
    snap = (await session.execute(snap_stmt)).scalar_one_or_none()
    if snap is None:
        return PaginatedResponse(items=[], total=0, limit=limit, offset=offset)
    cmt_stmt = (
        select(CommentDB)
        .where(CommentDB.snapshot_id == snap.id)
        .order_by(CommentDB.like_count.desc())
    )
    total = len((await session.execute(cmt_stmt)).scalars().all())
    rows = (await session.execute(cmt_stmt.limit(limit).offset(offset))).scalars().all()
    items = [_comment_to_response(c) for c in rows]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/persons/{person_id}", response_model=Person)
async def get_person(
    person_id: str,
    session: "AsyncSession" = Depends(get_async_session),
):
    person = await session.get(PersonDB, _uuid(person_id))
    if person is None:
        raise HTTPException(status_code=404, detail="person not found")
    link_stmt = select(PersonChannelDB).where(PersonChannelDB.person_id == person.id)
    links = (await session.execute(link_stmt)).scalars().all()
    return Person(
        id=str(person.id),
        display_name=person.display_name,
        summary=person.summary,
        identity_confidence=person.identity_confidence,
        channels=[
            PersonChannelLink(
                person_id=str(l.person_id),
                channel_id=str(l.channel_id),
                confidence=l.confidence,
                signals=[MatchSignal.model_validate(s) for s in (l.signals or [])],
            )
            for l in links
        ],
    )


@router.post("/persons/merge", response_model=Person)
async def merge_persons(
    req: MergePersonsRequest,
    session: "AsyncSession" = Depends(get_async_session),
):
    src = await session.get(PersonDB, _uuid(req.source_person_id))
    tgt = await session.get(PersonDB, _uuid(req.target_person_id))
    if src is None or tgt is None:
        raise HTTPException(status_code=404, detail="person not found")
    link_stmt = select(PersonChannelDB).where(PersonChannelDB.person_id == src.id)
    for link in (await session.execute(link_stmt)).scalars().all():
        link.person_id = tgt.id
    await session.delete(src)
    await session.flush()
    return await get_person(str(tgt.id), session)


@router.get("/videos/{video_id}/similar", response_model=list[VideoSimilarity])
async def list_similar(
    video_id: str,
    limit: int = 10,
    session: "AsyncSession" = Depends(get_async_session),
):
    vid = _uuid(video_id)
    stmt = (
        select(SimilarityDB)
        .where(or_(SimilarityDB.video_a_id == vid, SimilarityDB.video_b_id == vid))
        .order_by(SimilarityDB.score.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    out: list[VideoSimilarity] = []
    for r in rows:
        other = r.video_b_id if r.video_a_id == vid else r.video_a_id
        out.append(VideoSimilarity(video_id=str(other), score=r.score))
    return out


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid uuid") from exc
