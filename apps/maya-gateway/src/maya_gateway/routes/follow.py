"""Operator-facing follow-graph endpoints.

These are the routes the Homepage "Following" panel calls. They sit
alongside the existing ``/api/feeds/*`` ingest-facing routes but operate
at a different level:

- ``/api/feeds/subscribe`` — "tell the FeedPoller to start polling this
  channel" (one row per channel, no per-operator state).
- ``/api/follow/*`` — "I, operator X, want this Person/Channel on my
  Following tree with these notification prefs" (N rows per channel,
  one per operator).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from maya_contracts import (
    AttachChannelRequest,
    Channel as ChannelContract,
    CreatePersonRequest,
    FetchCadence,
    FollowRef,
    FollowRequest,
    FollowTreeResponse,
    PersonRef,
    Platform,
    ResolveChannelRequest,
    ResolveChannelResponse,
    UpdateFollowRequest,
    UpdatePersonRequest,
)
from maya_db import get_async_session

from maya_gateway.services.follow import FollowRepository, resolve_channel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/follow", tags=["follow"])

# v1 ships a single hardcoded operator: the user running this browser. The
# Following panel hardcodes the same value in follow-api.ts. Multi-operator
# support is wired into the schema but not exposed at the route layer yet.
DEFAULT_OPERATOR_ID = "local"


def _channel_to_contract(c) -> ChannelContract:  # noqa: ANN001 - sqla model
    return ChannelContract(
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


def _person_to_contract(p, channels) -> PersonRef:  # noqa: ANN001
    return PersonRef(
        id=p.id,
        slug=p.slug or "",
        display_name=p.display_name,
        kind=p.kind or "REAL",
        realm=p.realm,
        summary=p.summary,
        identity_confidence=p.identity_confidence,
        channels=[_channel_to_contract(c) for c in channels],
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _follow_to_contract(f) -> FollowRef:  # noqa: ANN001
    return FollowRef(
        id=f.id,
        operator_id=f.operator_id,
        subject_type=f.subject_type,
        subject_id=f.subject_id,
        cadence=FetchCadence(f.cadence),
        notify_homepage=f.notify_homepage,
        notify_discord=f.notify_discord,
        mpv_autolaunch=f.mpv_autolaunch,
        muted=f.muted,
        last_notified_at=f.last_notified_at,
        created_at=f.created_at,
    )


# ---------- Tree ----------


@router.get("/tree", response_model=FollowTreeResponse)
async def get_tree(
    operator_id: str = DEFAULT_OPERATOR_ID,
    session: "AsyncSession" = Depends(get_async_session),
) -> FollowTreeResponse:
    repo = FollowRepository(session)
    return await repo.build_tree(operator_id)


# ---------- Persons ----------


@router.post("/persons", response_model=PersonRef)
async def create_person(
    req: CreatePersonRequest,
    session: "AsyncSession" = Depends(get_async_session),
) -> PersonRef:
    repo = FollowRepository(session)
    existing = await repo.get_person_by_slug(req.slug)
    if existing is not None:
        raise HTTPException(status_code=409, detail="slug already in use")
    person = await repo.create_person(req)
    return _person_to_contract(person, [])


@router.get("/persons/{person_id}", response_model=PersonRef)
async def get_person(
    person_id: UUID,
    session: "AsyncSession" = Depends(get_async_session),
) -> PersonRef:
    repo = FollowRepository(session)
    person = await repo.get_person(person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="person not found")
    channels = await repo.list_channels_for_person(person.id)
    return _person_to_contract(person, channels)


@router.patch("/persons/{person_id}", response_model=PersonRef)
async def update_person(
    person_id: UUID,
    req: UpdatePersonRequest,
    session: "AsyncSession" = Depends(get_async_session),
) -> PersonRef:
    repo = FollowRepository(session)
    person = await repo.get_person(person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="person not found")
    person = await repo.update_person(person, req)
    channels = await repo.list_channels_for_person(person.id)
    return _person_to_contract(person, channels)


@router.delete("/persons/{person_id}")
async def delete_person(
    person_id: UUID,
    session: "AsyncSession" = Depends(get_async_session),
) -> dict[str, str]:
    repo = FollowRepository(session)
    person = await repo.get_person(person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="person not found")
    await repo.soft_delete_person(person)
    return {"id": str(person_id), "status": "deleted"}


# ---------- Resolve ----------


@router.post("/resolve", response_model=ResolveChannelResponse)
async def resolve(req: ResolveChannelRequest) -> ResolveChannelResponse:
    try:
        return resolve_channel(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------- Channels (attach/detach via person junction) ----------


@router.post("/persons/{person_id}/channels", response_model=ChannelContract)
async def attach_channel(
    person_id: UUID,
    req: AttachChannelRequest,
    session: "AsyncSession" = Depends(get_async_session),
) -> ChannelContract:
    repo = FollowRepository(session)
    person = await repo.get_person(person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="person not found")
    try:
        channel = await repo.attach_channel(person.id, req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _channel_to_contract(channel)


@router.delete("/persons/{person_id}/channels/{channel_id}")
async def detach_channel(
    person_id: UUID,
    channel_id: UUID,
    session: "AsyncSession" = Depends(get_async_session),
) -> dict[str, str]:
    repo = FollowRepository(session)
    person = await repo.get_person(person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="person not found")
    try:
        await repo.detach_channel(person.id, channel_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"person_id": str(person_id), "channel_id": str(channel_id), "status": "detached"}


# ---------- Follows ----------


@router.post("/follows", response_model=FollowRef)
async def follow(
    req: FollowRequest,
    operator_id: str = DEFAULT_OPERATOR_ID,
    session: "AsyncSession" = Depends(get_async_session),
) -> FollowRef:
    repo = FollowRepository(session)
    f = await repo.follow(operator_id, req)
    return _follow_to_contract(f)


@router.patch("/follows/{follow_id}", response_model=FollowRef)
async def update_follow(
    follow_id: UUID,
    req: UpdateFollowRequest,
    session: "AsyncSession" = Depends(get_async_session),
) -> FollowRef:
    repo = FollowRepository(session)
    f = await repo.get_follow(follow_id)
    if f is None:
        raise HTTPException(status_code=404, detail="follow not found")
    f = await repo.update_follow(f, req)
    return _follow_to_contract(f)


@router.delete("/follows/{follow_id}")
async def delete_follow(
    follow_id: UUID,
    session: "AsyncSession" = Depends(get_async_session),
) -> dict[str, str]:
    repo = FollowRepository(session)
    f = await repo.get_follow(follow_id)
    if f is None:
        raise HTTPException(status_code=404, detail="follow not found")
    await repo.soft_delete_follow(f)
    return {"id": str(follow_id), "status": "unfollowed"}
