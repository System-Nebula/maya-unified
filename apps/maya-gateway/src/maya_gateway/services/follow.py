"""Operator-facing follow-graph repository + tree builder.

Read path:
  build_tree(session, operator_id) -> FollowTreeResponse
    Joins persons + their attached channels + the operator's follow rows
    into the disclosure tree the Following panel renders. Computes
    EffectiveFollow for each channel by overlaying any channel-level row
    on top of the person-level row.

Write path:
  Person CRUD, attach/detach Channel via the feed_person_channels junction,
  Follow CRUD (subscribe / update prefs / soft unsubscribe).

Resolve is delegated to :mod:`maya_gateway.services.follow_resolve` which
is pure string parsing — no network. The tree builder *does not* hit the
platform adapters; operators see the cached metadata snapshot from the
last enrichment pass.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from maya_contracts import (
    AttachChannelRequest,
    Channel as ChannelContract,
    CreatePersonRequest,
    EffectiveFollow,
    FetchCadence,
    FollowRef,
    FollowRequest,
    FollowTreeChannel,
    FollowTreeNode,
    FollowTreeResponse,
    PersonRef,
    Platform,
    ResolveChannelRequest,
    ResolveChannelResponse,
    UpdateFollowRequest,
    UpdatePersonRequest,
)
from maya_db import (
    Channel as ChannelDB,
    Follow as FollowDB,
    Person as PersonDB,
    PersonChannel as PersonChannelDB,
    Subscription as SubscriptionDB,
)
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from maya_gateway.services.follow_resolve import resolve as _resolve_input


async def ensure_subscription(
    session: AsyncSession,
    channel_id: UUID,
    *,
    cadence: str = "weekly",
) -> None:
    """Ensure ingest polls a channel when an operator follows it."""
    existing = (
        await session.execute(
            select(SubscriptionDB).where(SubscriptionDB.channel_id == channel_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.enabled = True
        existing.cadence = cadence
        await session.flush()
        return
    session.add(
        SubscriptionDB(
            channel_id=channel_id,
            cadence=cadence,
            enabled=True,
        )
    )
    await session.flush()


async def ensure_subscriptions_for_follow(
    session: AsyncSession,
    subject_type: str,
    subject_id: UUID,
    *,
    cadence: str = "weekly",
) -> None:
    if subject_type == "CHANNEL":
        await ensure_subscription(session, subject_id, cadence=cadence)
        return
    links = (
        await session.execute(
            select(PersonChannelDB.channel_id).where(
                PersonChannelDB.person_id == subject_id
            )
        )
    ).scalars().all()
    for channel_id in links:
        await ensure_subscription(session, channel_id, cadence=cadence)


def _channel_to_contract(c: ChannelDB) -> ChannelContract:
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


def _person_to_contract(p: PersonDB, channels: list[ChannelDB]) -> PersonRef:
    return PersonRef(
        id=p.id,
        slug=p.slug or "",
        display_name=p.display_name,
        kind=p.kind or "REAL",  # type: ignore[arg-type]
        realm=p.realm,
        summary=p.summary,
        identity_confidence=p.identity_confidence,
        channels=[_channel_to_contract(c) for c in channels],
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _follow_to_contract(f: FollowDB) -> FollowRef:
    return FollowRef(
        id=f.id,
        operator_id=f.operator_id,
        subject_type=f.subject_type,  # type: ignore[arg-type]
        subject_id=f.subject_id,
        cadence=FetchCadence(f.cadence),
        notify_homepage=f.notify_homepage,
        notify_discord=f.notify_discord,
        mpv_autolaunch=f.mpv_autolaunch,
        muted=f.muted,
        last_notified_at=f.last_notified_at,
        created_at=f.created_at,
    )


def compute_effective(
    channel_id: UUID,
    person_follow: Optional[FollowDB],
    channel_follow: Optional[FollowDB],
) -> EffectiveFollow:
    """Overlay channel-level follow on person-level follow.

    Precedence: channel-level wins for any field it sets. If the
    channel-level row exists, ``source`` is CHANNEL even when the
    person-level row provided the inherited defaults — this is what the
    UI uses to decide whether to show "Override at channel" vs
    "Inherits from person".
    """

    if channel_follow is not None:
        tracking = not channel_follow.muted
        return EffectiveFollow(
            channel_id=channel_id,
            tracking=tracking,
            source="CHANNEL",
            cadence=FetchCadence(channel_follow.cadence),
            notify_homepage=channel_follow.notify_homepage,
            notify_discord=channel_follow.notify_discord,
            mpv_autolaunch=channel_follow.mpv_autolaunch,
            muted=channel_follow.muted,
        )

    if person_follow is not None:
        tracking = not person_follow.muted
        return EffectiveFollow(
            channel_id=channel_id,
            tracking=tracking,
            source="PERSON",
            cadence=FetchCadence(person_follow.cadence),
            notify_homepage=person_follow.notify_homepage,
            notify_discord=person_follow.notify_discord,
            mpv_autolaunch=person_follow.mpv_autolaunch,
            muted=person_follow.muted,
        )

    return EffectiveFollow(
        channel_id=channel_id,
        tracking=False,
        source="NONE",
    )


class FollowRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------- Person ----------

    async def list_persons(self) -> list[PersonDB]:
        result = await self.session.execute(
            select(PersonDB)
            .where(PersonDB.deleted_at.is_(None))
            .order_by(PersonDB.display_name.asc())
        )
        return list(result.scalars().all())

    async def get_person(self, person_id: UUID) -> Optional[PersonDB]:
        result = await self.session.execute(
            select(PersonDB).where(
                and_(PersonDB.id == person_id, PersonDB.deleted_at.is_(None))
            )
        )
        return result.scalar_one_or_none()

    async def get_person_by_slug(self, slug: str) -> Optional[PersonDB]:
        result = await self.session.execute(
            select(PersonDB).where(
                and_(PersonDB.slug == slug, PersonDB.deleted_at.is_(None))
            )
        )
        return result.scalar_one_or_none()

    async def create_person(self, req: CreatePersonRequest) -> PersonDB:
        person = PersonDB(
            slug=req.slug,
            display_name=req.display_name,
            kind=req.kind,
            realm=req.realm,
            summary=req.summary,
            identity_confidence=0.0,
        )
        self.session.add(person)
        await self.session.flush()
        return person

    async def update_person(
        self, person: PersonDB, req: UpdatePersonRequest
    ) -> PersonDB:
        if req.display_name is not None:
            person.display_name = req.display_name
        if req.kind is not None:
            person.kind = req.kind
        if req.realm is not None:
            person.realm = req.realm
        if req.summary is not None:
            person.summary = req.summary
        await self.session.flush()
        return person

    async def soft_delete_person(self, person: PersonDB) -> None:
        person.deleted_at = datetime.now(timezone.utc)
        await self.session.flush()

    # ---------- Channel attach/detach ----------

    async def list_channels_for_person(
        self, person_id: UUID
    ) -> list[ChannelDB]:
        result = await self.session.execute(
            select(ChannelDB)
            .join(PersonChannelDB, PersonChannelDB.channel_id == ChannelDB.id)
            .where(
                and_(
                    PersonChannelDB.person_id == person_id,
                    ChannelDB.deleted_at.is_(None),
                )
            )
            .order_by(ChannelDB.platform.asc(), ChannelDB.handle.asc())
        )
        return list(result.scalars().all())

    async def get_channel(self, channel_id: UUID) -> Optional[ChannelDB]:
        result = await self.session.execute(
            select(ChannelDB).where(
                and_(ChannelDB.id == channel_id, ChannelDB.deleted_at.is_(None))
            )
        )
        return result.scalar_one_or_none()

    async def find_channel_by_platform_id(
        self, platform: Platform, platform_id: str
    ) -> Optional[ChannelDB]:
        result = await self.session.execute(
            select(ChannelDB).where(
                and_(
                    ChannelDB.platform == platform.value,
                    ChannelDB.platform_id == platform_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def attach_channel(
        self,
        person_id: UUID,
        req: AttachChannelRequest,
    ) -> ChannelDB:
        channel = await self._resolve_or_get_channel(req)
        # Idempotent: re-attaching is a no-op.
        existing = await self.session.execute(
            select(PersonChannelDB).where(
                and_(
                    PersonChannelDB.person_id == person_id,
                    PersonChannelDB.channel_id == channel.id,
                )
            )
        )
        link = existing.scalar_one_or_none()
        if link is None:
            link = PersonChannelDB(
                person_id=person_id,
                channel_id=channel.id,
                confidence=req.confidence,
                signals=[s.model_dump() for s in req.signals],
            )
            self.session.add(link)
        else:
            link.confidence = req.confidence
            link.signals = [s.model_dump() for s in req.signals]
        await self.session.flush()
        return channel

    async def _resolve_or_get_channel(
        self, req: AttachChannelRequest
    ) -> ChannelDB:
        if req.channel_id is not None:
            channel = await self.get_channel(req.channel_id)
            if channel is None:
                raise ValueError("channel_id does not exist")
            return channel

        if req.resolve is None:
            raise ValueError("attach requires either channel_id or resolve")

        preview_resp = resolve_channel(req.resolve)
        preview = preview_resp.channel
        existing = await self.find_channel_by_platform_id(
            preview.platform, preview.platform_id
        )
        if existing is not None:
            return existing
        channel = ChannelDB(
            platform=preview.platform.value,
            platform_id=preview.platform_id,
            handle=preview.handle,
            display_name=preview.display_name,
            feed_url=preview.feed_url,
            cadence="weekly",
        )
        self.session.add(channel)
        await self.session.flush()
        return channel

    async def detach_channel(
        self, person_id: UUID, channel_id: UUID
    ) -> None:
        result = await self.session.execute(
            select(PersonChannelDB).where(
                and_(
                    PersonChannelDB.person_id == person_id,
                    PersonChannelDB.channel_id == channel_id,
                )
            )
        )
        link = result.scalar_one_or_none()
        if link is None:
            raise ValueError("channel is not attached to this person")
        await self.session.delete(link)
        await self.session.flush()

    # ---------- Follow CRUD ----------

    async def follow(self, operator_id: str, req: FollowRequest) -> FollowDB:
        # Resurrect a soft-deleted row instead of inserting a duplicate.
        existing = await self.session.execute(
            select(FollowDB).where(
                and_(
                    FollowDB.operator_id == operator_id,
                    FollowDB.subject_type == req.subject_type,
                    FollowDB.subject_id == req.subject_id,
                    FollowDB.deleted_at.is_(None),
                )
            )
        )
        live = existing.scalar_one_or_none()
        if live is not None:
            live.cadence = req.cadence.value
            live.notify_homepage = req.notify_homepage
            live.notify_discord = req.notify_discord
            live.mpv_autolaunch = req.mpv_autolaunch
            live.muted = req.muted
            await self.session.flush()
            await ensure_subscriptions_for_follow(
                self.session,
                req.subject_type.value,
                req.subject_id,
                cadence=req.cadence.value,
            )
            return live

        follow = FollowDB(
            operator_id=operator_id,
            subject_type=req.subject_type.value,
            subject_id=req.subject_id,
            cadence=req.cadence.value,
            notify_homepage=req.notify_homepage,
            notify_discord=req.notify_discord,
            mpv_autolaunch=req.mpv_autolaunch,
            muted=req.muted,
        )
        self.session.add(follow)
        await self.session.flush()
        await ensure_subscriptions_for_follow(
            self.session,
            req.subject_type.value,
            req.subject_id,
            cadence=req.cadence.value,
        )
        return follow

    async def get_follow(self, follow_id: UUID) -> Optional[FollowDB]:
        result = await self.session.execute(
            select(FollowDB).where(
                and_(FollowDB.id == follow_id, FollowDB.deleted_at.is_(None))
            )
        )
        return result.scalar_one_or_none()

    async def update_follow(
        self, follow: FollowDB, req: UpdateFollowRequest
    ) -> FollowDB:
        if req.cadence is not None:
            follow.cadence = req.cadence.value
        if req.notify_homepage is not None:
            follow.notify_homepage = req.notify_homepage
        if req.notify_discord is not None:
            follow.notify_discord = req.notify_discord
        if req.mpv_autolaunch is not None:
            follow.mpv_autolaunch = req.mpv_autolaunch
        if req.muted is not None:
            follow.muted = req.muted
        await self.session.flush()
        return follow

    async def soft_delete_follow(self, follow: FollowDB) -> None:
        follow.deleted_at = datetime.now(timezone.utc)
        await self.session.flush()

    # ---------- Tree builder ----------

    async def build_tree(self, operator_id: str) -> FollowTreeResponse:
        persons = await self.list_persons()
        person_ids = [p.id for p in persons]
        if not person_ids:
            return FollowTreeResponse(operator_id=operator_id, nodes=[])

        link_result = await self.session.execute(
            select(PersonChannelDB.person_id, ChannelDB)
            .join(ChannelDB, ChannelDB.id == PersonChannelDB.channel_id)
            .where(
                and_(
                    PersonChannelDB.person_id.in_(person_ids),
                    ChannelDB.deleted_at.is_(None),
                )
            )
        )
        channels_by_person: dict[UUID, list[ChannelDB]] = {pid: [] for pid in person_ids}
        all_channel_ids: list[UUID] = []
        for person_id, channel in link_result.all():
            channels_by_person[person_id].append(channel)
            all_channel_ids.append(channel.id)

        subject_ids = [*person_ids, *all_channel_ids]
        follows: list[FollowDB] = []
        if subject_ids:
            f_result = await self.session.execute(
                select(FollowDB).where(
                    and_(
                        FollowDB.operator_id == operator_id,
                        FollowDB.deleted_at.is_(None),
                        FollowDB.subject_id.in_(subject_ids),
                    )
                )
            )
            follows = list(f_result.scalars().all())

        return assemble_tree(operator_id, persons, channels_by_person, follows)


def assemble_tree(
    operator_id: str,
    persons: list[PersonDB],
    channels_by_person: dict[UUID, list[ChannelDB]],
    follows: list[FollowDB],
) -> FollowTreeResponse:
    """Pure overlay function — combines pre-loaded rows into the tree.

    Split from :meth:`FollowRepository.build_tree` so the assembly logic is
    unit-testable without spinning up a database session. The repo handles
    SQL; this handles the in-memory join.
    """

    person_follow_by_id: dict[UUID, FollowDB] = {
        f.subject_id: f for f in follows if f.subject_type == "PERSON"
    }
    channel_follow_by_id: dict[UUID, FollowDB] = {
        f.subject_id: f for f in follows if f.subject_type == "CHANNEL"
    }

    nodes: list[FollowTreeNode] = []
    for person in persons:
        channels = sorted(
            channels_by_person.get(person.id, []),
            key=lambda c: (c.platform, c.handle),
        )
        person_follow = person_follow_by_id.get(person.id)
        tree_channels: list[FollowTreeChannel] = []
        for ch in channels:
            ch_follow = channel_follow_by_id.get(ch.id)
            effective = compute_effective(ch.id, person_follow, ch_follow)
            tree_channels.append(
                FollowTreeChannel(
                    channel=_channel_to_contract(ch),
                    follow=_follow_to_contract(ch_follow) if ch_follow else None,
                    effective=effective,
                )
            )
        nodes.append(
            FollowTreeNode(
                person=_person_to_contract(person, channels),
                person_follow=_follow_to_contract(person_follow)
                if person_follow
                else None,
                channels=tree_channels,
            )
        )
    return FollowTreeResponse(operator_id=operator_id, nodes=nodes)


def resolve_channel(req: ResolveChannelRequest) -> ResolveChannelResponse:
    """Public re-export so route handlers can call resolve without importing
    the inner ``follow_resolve`` module directly."""
    return _resolve_input(req)


__all__ = [
    "FollowRepository",
    "assemble_tree",
    "compute_effective",
    "ensure_subscription",
    "ensure_subscriptions_for_follow",
    "resolve_channel",
]
