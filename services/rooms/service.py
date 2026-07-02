"""Public multi-user voice rooms — create, join, chat, voice queue."""

from __future__ import annotations

import logging
import re
import secrets
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from maya_db import get_async_session
from maya_db.models.voice_room import VoiceRoom, VoiceRoomMember, VoiceRoomMessage, VoiceRoomVoiceQueue
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.operator_voice.paths import (
    load_legacy_global_settings,
    load_operator_personalities_file,
    load_operator_settings_file,
)
from services.rooms.guest_session import hash_guest_token, sign_guest_session

log = logging.getLogger("maya-unified.rooms")

_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def _slugify(name: str) -> str:
    base = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-") or "room"
    return f"{base}-{secrets.token_hex(3)}"


async def _commit(session: AsyncSession):
    await session.commit()


async def create_room(
    session: AsyncSession,
    owner_id: str | uuid.UUID,
    *,
    name: str,
    description: str = "",
    visibility: str = "private",
    personality_slug: str | None = None,
) -> VoiceRoom:
    settings = load_operator_settings_file(owner_id) or load_legacy_global_settings()
    pers = load_operator_personalities_file(owner_id)
    active = personality_slug or pers.get("active") or "default"
    personalities = pers.get("personalities") or {}
    personality_snapshot = personalities.get(active) or {}
    room = VoiceRoom(
        slug=_slugify(name),
        name=name.strip(),
        description=(description or "").strip(),
        owner_operator_id=uuid.UUID(str(owner_id)),
        visibility=visibility if visibility in ("public", "private") else "private",
        status="open",
        personality_snapshot={"active": active, "entry": personality_snapshot},
        settings_snapshot=deepcopy(settings),
    )
    session.add(room)
    await session.flush()
    owner_member = VoiceRoomMember(
        room_id=room.id,
        operator_id=uuid.UUID(str(owner_id)),
        display_name="Owner",
        role="owner",
    )
    session.add(owner_member)
    await session.flush()
    return room


async def get_room_by_slug(session: AsyncSession, slug: str) -> VoiceRoom | None:
    return await session.scalar(select(VoiceRoom).where(VoiceRoom.slug == slug.strip().lower()))


async def active_member_count(session: AsyncSession, room_id: uuid.UUID) -> int:
    result = await session.scalar(
        select(func.count())
        .select_from(VoiceRoomMember)
        .where(VoiceRoomMember.room_id == room_id, VoiceRoomMember.left_at.is_(None))
    )
    return int(result or 0)


def room_availability(room: VoiceRoom, member_count: int) -> dict[str, Any]:
    available = (
        room.visibility == "public"
        and room.status == "open"
        and member_count < room.max_participants
    )
    return {
        "available": available,
        "visibility": room.visibility,
        "status": room.status,
        "member_count": member_count,
        "max_participants": room.max_participants,
    }


async def join_room_operator(
    session: AsyncSession, room: VoiceRoom, operator_id: str | uuid.UUID, display_name: str
) -> VoiceRoomMember:
    oid = uuid.UUID(str(operator_id))
    existing = await session.scalar(
        select(VoiceRoomMember).where(
            VoiceRoomMember.room_id == room.id,
            VoiceRoomMember.operator_id == oid,
            VoiceRoomMember.left_at.is_(None),
        )
    )
    if existing:
        return existing
    count = await active_member_count(session, room.id)
    if count >= room.max_participants:
        raise ValueError("room is full")
    if room.visibility != "public" and room.owner_operator_id != oid:
        raise ValueError("room is private")
    member = VoiceRoomMember(
        room_id=room.id,
        operator_id=oid,
        display_name=display_name.strip() or "Operator",
        role="owner" if room.owner_operator_id == oid else "member",
    )
    session.add(member)
    await session.flush()
    return member


async def join_room_guest(
    session: AsyncSession, room: VoiceRoom, display_name: str
) -> tuple[VoiceRoomMember, str]:
    if room.visibility != "public" or room.status != "open":
        raise ValueError("room not available")
    count = await active_member_count(session, room.id)
    if count >= room.max_participants:
        raise ValueError("room is full")
    token = secrets.token_urlsafe(24)
    member = VoiceRoomMember(
        room_id=room.id,
        guest_token_hash=hash_guest_token(token),
        display_name=(display_name or "Guest").strip()[:128],
        role="member",
    )
    session.add(member)
    await session.flush()
    cookie = sign_guest_session(str(member.id), str(room.id))
    return member, cookie


async def leave_room(session: AsyncSession, member_id: str | uuid.UUID) -> None:
    member = await session.get(VoiceRoomMember, uuid.UUID(str(member_id)))
    if member and member.left_at is None:
        member.left_at = datetime.now(timezone.utc)
        await session.flush()


async def append_room_message(
    session: AsyncSession,
    room_id: uuid.UUID,
    member_id: uuid.UUID | None,
    role: str,
    content: str,
) -> VoiceRoomMessage:
    msg = VoiceRoomMessage(
        room_id=room_id,
        member_id=member_id,
        role=role,
        content=content.strip(),
        ts=datetime.now(timezone.utc),
    )
    session.add(msg)
    await session.flush()
    return msg


async def get_room_messages(
    session: AsyncSession, room_id: uuid.UUID, *, since_id: int = 0, limit: int = 200
) -> list[dict[str, Any]]:
    q = (
        select(VoiceRoomMessage)
        .where(VoiceRoomMessage.room_id == room_id)
        .order_by(VoiceRoomMessage.ts.asc())
        .limit(limit)
    )
    if since_id > 0:
        q = q.where(VoiceRoomMessage.id > since_id)
    rows = await session.scalars(q)
    out: list[dict[str, Any]] = []
    for row in rows.all():
        out.append(
            {
                "id": row.id,
                "role": row.role,
                "content": row.content,
                "member_id": str(row.member_id) if row.member_id else None,
                "ts": row.ts.isoformat() if row.ts else None,
            }
        )
    return out


async def room_history_messages(session: AsyncSession, room_id: uuid.UUID, *, limit: int = 40) -> list[dict]:
    rows = await session.scalars(
        select(VoiceRoomMessage)
        .where(VoiceRoomMessage.room_id == room_id, VoiceRoomMessage.role.in_(("user", "assistant")))
        .order_by(VoiceRoomMessage.ts.desc())
        .limit(limit)
    )
    items = list(reversed(rows.all()))
    return [{"role": r.role, "content": r.content} for r in items]


async def list_rooms_for_operator(session: AsyncSession, operator_id: str | uuid.UUID) -> list[VoiceRoom]:
    oid = uuid.UUID(str(operator_id))
    owned = await session.scalars(select(VoiceRoom).where(VoiceRoom.owner_operator_id == oid))
    public = await session.scalars(
        select(VoiceRoom).where(VoiceRoom.visibility == "public", VoiceRoom.status == "open")
    )
    seen: set[uuid.UUID] = set()
    out: list[VoiceRoom] = []
    for room in list(owned.all()) + list(public.all()):
        if room.id not in seen:
            seen.add(room.id)
            out.append(room)
    return out


async def request_speak(session: AsyncSession, room_id: uuid.UUID, member_id: uuid.UUID) -> VoiceRoomVoiceQueue:
    active = await session.scalar(
        select(VoiceRoomVoiceQueue).where(
            VoiceRoomVoiceQueue.room_id == room_id,
            VoiceRoomVoiceQueue.member_id == member_id,
            VoiceRoomVoiceQueue.status.in_(("waiting", "active")),
        )
    )
    if active:
        return active
    max_pos = await session.scalar(
        select(func.max(VoiceRoomVoiceQueue.position)).where(
            VoiceRoomVoiceQueue.room_id == room_id,
            VoiceRoomVoiceQueue.status == "waiting",
        )
    )
    entry = VoiceRoomVoiceQueue(
        room_id=room_id,
        member_id=member_id,
        position=int(max_pos or 0) + 1,
        status="waiting",
    )
    session.add(entry)
    await session.flush()
    return entry


async def get_queue_state(session: AsyncSession, room_id: uuid.UUID) -> dict[str, Any]:
    rows = await session.scalars(
        select(VoiceRoomVoiceQueue)
        .where(
            VoiceRoomVoiceQueue.room_id == room_id,
            VoiceRoomVoiceQueue.status.in_(("waiting", "active")),
        )
        .order_by(VoiceRoomVoiceQueue.position.asc())
    )
    items = rows.all()
    active = next((r for r in items if r.status == "active"), None)
    waiting = [r for r in items if r.status == "waiting"]
    return {
        "active_speaker_id": str(active.member_id) if active else None,
        "queue": [{"member_id": str(r.member_id), "position": r.position} for r in waiting],
        "queue_length": len(waiting),
    }


async def release_speaker(session: AsyncSession, room_id: uuid.UUID, member_id: uuid.UUID) -> None:
    active = await session.scalar(
        select(VoiceRoomVoiceQueue).where(
            VoiceRoomVoiceQueue.room_id == room_id,
            VoiceRoomVoiceQueue.member_id == member_id,
            VoiceRoomVoiceQueue.status == "active",
        )
    )
    if active:
        active.status = "done"
        active.ended_at = datetime.now(timezone.utc)
        await session.flush()


async def grant_next_speaker(session: AsyncSession, room_id: uuid.UUID) -> VoiceRoomVoiceQueue | None:
    current = await session.scalar(
        select(VoiceRoomVoiceQueue).where(
            VoiceRoomVoiceQueue.room_id == room_id,
            VoiceRoomVoiceQueue.status == "active",
        )
    )
    if current:
        current.status = "done"
        current.ended_at = datetime.now(timezone.utc)
    nxt = await session.scalar(
        select(VoiceRoomVoiceQueue)
        .where(VoiceRoomVoiceQueue.room_id == room_id, VoiceRoomVoiceQueue.status == "waiting")
        .order_by(VoiceRoomVoiceQueue.position.asc())
        .limit(1)
    )
    if nxt:
        nxt.status = "active"
        nxt.granted_at = datetime.now(timezone.utc)
        await session.flush()
    return nxt


async def get_member(session: AsyncSession, member_id: str | uuid.UUID) -> VoiceRoomMember | None:
    return await session.get(VoiceRoomMember, uuid.UUID(str(member_id)))


async def resolve_guest_member(session: AsyncSession, token_hash: str, room_id: uuid.UUID) -> VoiceRoomMember | None:
    return await session.scalar(
        select(VoiceRoomMember).where(
            VoiceRoomMember.room_id == room_id,
            VoiceRoomMember.guest_token_hash == token_hash,
            VoiceRoomMember.left_at.is_(None),
        )
    )
