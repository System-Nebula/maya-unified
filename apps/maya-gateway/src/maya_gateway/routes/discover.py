"""Discover feed API — unified What's New surface."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from maya_contracts import (
    ArtistActivityState,
    ArtistTrackerEntry,
    ArtistTrackerResponse,
    CollectionSummary,
    DiscoverEventsResponse,
    FeedResponse,
    InboxSummaryResponse,
    OperatorPreferences,
    OperatorPreferencesPatch,
    WantlistMatch,
)
from maya_db import (
    Follow as FollowDB,
    KnowledgeItem as KnowledgeItemDB,
    Notification as NotificationDB,
    Person as PersonDB,
    get_async_session,
)
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from maya_gateway.services.discover_query import parse_discover_query
from maya_gateway.services.discover_rank import (
    get_collection_summary,
    get_inbox_summary,
    get_or_create_preferences,
    patch_preferences,
    rank_feed,
)

router = APIRouter(prefix="/api/discover", tags=["discover"])

DEFAULT_OPERATOR_ID = "local"


@router.get("/feed", response_model=FeedResponse)
async def get_feed(
    cursor: Optional[str] = None,
    limit: int = 20,
    window: str = "7d",
    lane: Optional[str] = None,
    refresh: bool = False,  # noqa: ARG001 — client hint; ranker is stateless
    operator_id: str = DEFAULT_OPERATOR_ID,
    session: AsyncSession = Depends(get_async_session),
):
    prefs = await get_or_create_preferences(session, operator_id)
    effective_window = window or prefs.window_default
    return await rank_feed(
        session,
        operator_id,
        window=effective_window,
        cursor=cursor,
        limit=min(limit, 50),
        lane=lane,
    )


@router.get("/feed/ask", response_model=FeedResponse)
async def ask_feed(
    q: str,
    cursor: Optional[str] = None,
    limit: int = 20,
    operator_id: str = DEFAULT_OPERATOR_ID,
    session: AsyncSession = Depends(get_async_session),
):
    prefs = await get_or_create_preferences(session, operator_id)
    parsed = parse_discover_query(q, default_window=prefs.window_default)
    return await rank_feed(
        session,
        operator_id,
        window=parsed.window,
        cursor=cursor,
        limit=min(limit, 50),
        artist_slug=parsed.artist_slug,
    )


@router.get("/preferences", response_model=OperatorPreferences)
async def get_preferences(
    operator_id: str = DEFAULT_OPERATOR_ID,
    session: AsyncSession = Depends(get_async_session),
):
    return await get_or_create_preferences(session, operator_id)


@router.patch("/preferences", response_model=OperatorPreferences)
async def update_preferences(
    patch: OperatorPreferencesPatch,
    operator_id: str = DEFAULT_OPERATOR_ID,
    session: AsyncSession = Depends(get_async_session),
):
    return await patch_preferences(
        session,
        operator_id,
        genre_weights=patch.genre_weights,
        source_enabled=patch.source_enabled,
        source_trust=patch.source_trust,
        metro=patch.metro,
        window_default=patch.window_default,
    )


@router.get("/collection/summary", response_model=CollectionSummary)
async def collection_summary(
    operator_id: str = DEFAULT_OPERATOR_ID,
    session: AsyncSession = Depends(get_async_session),
):
    row = await get_collection_summary(session, operator_id)
    if row is None:
        return CollectionSummary(operator_id=operator_id)
    matches = [
        WantlistMatch(
            release_id=m.get("release_id", ""),
            title=m.get("title", ""),
            artist=m.get("artist", ""),
            url=m.get("url"),
        )
        for m in (row.wantlist_matches or [])
    ]
    return CollectionSummary(
        operator_id=row.operator_id,
        vinyl_count=row.vinyl_count,
        digital_count=row.digital_count,
        wantlist_matches=matches,
        synced_at=row.synced_at,
    )


@router.get("/inbox/summary", response_model=InboxSummaryResponse)
async def inbox_summary(
    window: str = "7d",
    operator_id: str = DEFAULT_OPERATOR_ID,
    session: AsyncSession = Depends(get_async_session),
):
    return await get_inbox_summary(session, operator_id, window=window)


@router.get("/events", response_model=DiscoverEventsResponse)
async def list_events(
    metro: str = "minneapolis",
    days: int = 30,
    operator_id: str = DEFAULT_OPERATOR_ID,  # noqa: ARG001
):
    # RA connector stub — returns empty until lib/sources RA adapter lands.
    return DiscoverEventsResponse(items=[], metro=metro)


@router.get("/artists/tracker", response_model=ArtistTrackerResponse)
async def artist_tracker(
    operator_id: str = DEFAULT_OPERATOR_ID,
    session: AsyncSession = Depends(get_async_session),
):
    follows = (
        await session.execute(
            select(FollowDB).where(
                and_(
                    FollowDB.operator_id == operator_id,
                    FollowDB.subject_type == "PERSON",
                    FollowDB.deleted_at.is_(None),
                    FollowDB.muted.is_(False),
                )
            )
        )
    ).scalars().all()
    if not follows:
        return ArtistTrackerResponse(items=[])

    person_ids = [f.subject_id for f in follows]
    persons = (
        await session.execute(
            select(PersonDB).where(
                and_(PersonDB.id.in_(person_ids), PersonDB.deleted_at.is_(None))
            )
        )
    ).scalars().all()

    latest_knowledge = (
        await session.execute(
            select(KnowledgeItemDB)
            .where(KnowledgeItemDB.operator_id == operator_id)
            .order_by(KnowledgeItemDB.received_at.desc())
            .limit(20)
        )
    ).scalars().all()
    knowledge_by_slug = {k.artist_slug: k for k in latest_knowledge}

    unread_notifications = (
        await session.execute(
            select(func.count())
            .select_from(NotificationDB)
            .where(
                and_(
                    NotificationDB.operator_id == operator_id,
                    NotificationDB.read.is_(False),
                    NotificationDB.kind == "artist_newsletter",
                )
            )
        )
    ).scalar_one()

    items: list[ArtistTrackerEntry] = []
    for person in persons:
        k = knowledge_by_slug.get(person.slug or "")
        unseen = unread_notifications > 0 and person.slug in knowledge_by_slug
        items.append(
            ArtistTrackerEntry(
                person_id=str(person.id),
                slug=person.slug or "",
                display_name=person.display_name,
                activity_state=ArtistActivityState.NEW_RELEASE
                if unseen
                else ArtistActivityState.IDLE,
                latest_title=k.title if k else None,
                latest_at=k.received_at if k else None,
                unseen=unseen,
                ontology_artist_id=str(k.ontology_artist_id) if k and k.ontology_artist_id else None,
            )
        )
    return ArtistTrackerResponse(items=items)
