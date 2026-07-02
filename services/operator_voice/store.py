"""Async Postgres CRUD for per-operator voice workspace."""

from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from maya_db.models.operator_voice import (
    OperatorConversationMessage,
    OperatorConversationSession,
    OperatorPersonalities,
    OperatorVoiceSettings,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.settings.schema import DEFAULT_SETTINGS, deep_merge

__all__ = [
    "get_or_create_settings",
    "save_settings",
    "get_or_create_personalities",
    "save_personalities",
    "get_or_create_session",
    "append_message",
    "get_conversation_turns",
    "history_as_messages",
]


async def get_or_create_settings(session: AsyncSession, operator_id: str | uuid.UUID) -> dict[str, Any]:
    oid = uuid.UUID(str(operator_id))
    row = await session.get(OperatorVoiceSettings, oid)
    if row is None:
        row = OperatorVoiceSettings(operator_id=oid, settings=deepcopy(DEFAULT_SETTINGS))
        session.add(row)
        await session.flush()
    return deepcopy(row.settings) if isinstance(row.settings, dict) else deepcopy(DEFAULT_SETTINGS)


async def save_settings(
    session: AsyncSession, operator_id: str | uuid.UUID, patch: dict[str, Any]
) -> dict[str, Any]:
    oid = uuid.UUID(str(operator_id))
    current = await get_or_create_settings(session, oid)
    merged = deep_merge(current, patch if isinstance(patch, dict) else {})
    row = await session.get(OperatorVoiceSettings, oid)
    if row is None:
        row = OperatorVoiceSettings(operator_id=oid, settings=merged)
        session.add(row)
    else:
        row.settings = merged
    await session.flush()
    return merged


async def get_or_create_personalities(session: AsyncSession, operator_id: str | uuid.UUID) -> dict[str, Any]:
    oid = uuid.UUID(str(operator_id))
    row = await session.get(OperatorPersonalities, oid)
    if row is None:
        row = OperatorPersonalities(
            operator_id=oid,
            active_slug="default",
            personalities={},
        )
        session.add(row)
        await session.flush()
    return {
        "active": row.active_slug or "",
        "personalities": deepcopy(row.personalities) if isinstance(row.personalities, dict) else {},
    }


async def save_personalities(
    session: AsyncSession,
    operator_id: str | uuid.UUID,
    *,
    active: str | None = None,
    personalities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    oid = uuid.UUID(str(operator_id))
    row = await session.get(OperatorPersonalities, oid)
    if row is None:
        row = OperatorPersonalities(operator_id=oid, active_slug="default", personalities={})
        session.add(row)
    if active is not None:
        row.active_slug = active
    if personalities is not None:
        row.personalities = personalities
    await session.flush()
    return {"active": row.active_slug, "personalities": deepcopy(row.personalities)}


async def get_or_create_session(session: AsyncSession, operator_id: str | uuid.UUID) -> uuid.UUID:
    oid = uuid.UUID(str(operator_id))
    result = await session.scalar(
        select(OperatorConversationSession)
        .where(
            OperatorConversationSession.operator_id == oid,
            OperatorConversationSession.ended_at.is_(None),
        )
        .order_by(OperatorConversationSession.started_at.desc())
        .limit(1)
    )
    if result is not None:
        return result.id
    sess = OperatorConversationSession(operator_id=oid, metadata_={})
    session.add(sess)
    await session.flush()
    return sess.id


async def append_message(
    session: AsyncSession,
    operator_id: str | uuid.UUID,
    role: str,
    content: str,
) -> None:
    content = (content or "").strip()
    if not content:
        return
    oid = uuid.UUID(str(operator_id))
    session_id = await get_or_create_session(session, oid)
    msg = OperatorConversationMessage(
        session_id=session_id,
        operator_id=oid,
        role=role,
        content=content,
        ts=datetime.now(timezone.utc),
    )
    session.add(msg)
    await session.flush()


async def get_conversation_turns(
    session: AsyncSession,
    operator_id: str | uuid.UUID,
    *,
    limit: int = 200,
) -> list[dict[str, str]]:
    oid = uuid.UUID(str(operator_id))
    session_id = await get_or_create_session(session, oid)
    rows = await session.scalars(
        select(OperatorConversationMessage)
        .where(OperatorConversationMessage.session_id == session_id)
        .order_by(OperatorConversationMessage.ts.asc())
        .limit(limit)
    )
    turns: list[dict[str, str]] = []
    for row in rows.all():
        role = row.role
        if role == "user":
            turns.append({"role": "operator", "text": row.content})
        elif role == "assistant":
            turns.append({"role": "maya", "text": row.content})
        else:
            turns.append({"role": role, "text": row.content})
    return turns


async def history_as_messages(
    session: AsyncSession,
    operator_id: str | uuid.UUID,
    *,
    limit: int = 40,
) -> list[dict[str, str]]:
    """LLM history format [{role, content}, ...]."""
    oid = uuid.UUID(str(operator_id))
    session_id = await get_or_create_session(session, oid)
    rows = await session.scalars(
        select(OperatorConversationMessage)
        .where(OperatorConversationMessage.session_id == session_id)
        .order_by(OperatorConversationMessage.ts.desc())
        .limit(limit)
    )
    items = list(reversed(rows.all()))
    return [{"role": r.role, "content": r.content} for r in items]


async def list_conversation_messages(
    session: AsyncSession,
    operator_id: str | uuid.UUID,
    *,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    oid = uuid.UUID(str(operator_id))
    total = await session.scalar(
        select(func.count())
        .select_from(OperatorConversationMessage)
        .where(OperatorConversationMessage.operator_id == oid)
    )
    rows = await session.scalars(
        select(OperatorConversationMessage)
        .where(OperatorConversationMessage.operator_id == oid)
        .order_by(OperatorConversationMessage.ts.desc())
        .offset(offset)
        .limit(limit)
    )
    messages = [
        {
            "id": r.id,
            "session_id": str(r.session_id),
            "role": r.role,
            "content": r.content,
            "ts": r.ts.isoformat() if r.ts else None,
        }
        for r in rows.all()
    ]
    return {"total": total or 0, "messages": messages}


async def clear_conversation(session: AsyncSession, operator_id: str | uuid.UUID) -> int:
    oid = uuid.UUID(str(operator_id))
    result = await session.execute(
        select(OperatorConversationMessage).where(OperatorConversationMessage.operator_id == oid)
    )
    messages = list(result.scalars().all())
    for msg in messages:
        await session.delete(msg)
    sessions = await session.scalars(
        select(OperatorConversationSession).where(OperatorConversationSession.operator_id == oid)
    )
    for sess in sessions.all():
        await session.delete(sess)
    await session.flush()
    return len(messages)


async def delete_personality_slug(
    session: AsyncSession, operator_id: str | uuid.UUID, slug: str
) -> dict[str, Any]:
    slug = (slug or "").strip()
    if not slug:
        raise ValueError("personality slug required")
    data = await get_or_create_personalities(session, operator_id)
    personalities = data.get("personalities") or {}
    if slug not in personalities:
        raise ValueError(f"personality {slug!r} not found")
    del personalities[slug]
    active = data.get("active") or ""
    if active == slug:
        active = next(iter(personalities), "")
    return await save_personalities(
        session, operator_id, active=active, personalities=personalities
    )


async def set_personality_flag(
    session: AsyncSession,
    operator_id: str | uuid.UUID,
    slug: str,
    *,
    flagged: bool,
) -> dict[str, Any]:
    slug = (slug or "").strip()
    if not slug:
        raise ValueError("personality slug required")
    data = await get_or_create_personalities(session, operator_id)
    personalities = data.get("personalities") or {}
    if slug not in personalities:
        raise ValueError(f"personality {slug!r} not found")
    entry = personalities[slug]
    if not isinstance(entry, dict):
        entry = {"name": slug}
    entry["flagged"] = bool(flagged)
    personalities[slug] = entry
    return await save_personalities(session, operator_id, personalities=personalities)


async def workspace_stats(session: AsyncSession, operator_id: str | uuid.UUID) -> dict[str, int]:
    oid = uuid.UUID(str(operator_id))
    msg_count = await session.scalar(
        select(func.count())
        .select_from(OperatorConversationMessage)
        .where(OperatorConversationMessage.operator_id == oid)
    )
    pers = await get_or_create_personalities(session, oid)
    personalities = pers.get("personalities") or {}
    flagged = sum(
        1 for p in personalities.values() if isinstance(p, dict) and p.get("flagged")
    )
    return {
        "message_count": msg_count or 0,
        "personality_count": len(personalities),
        "flagged_personality_count": flagged,
    }


async def any_operator_settings_exist(session: AsyncSession) -> bool:
    result = await session.scalar(select(func.count()).select_from(OperatorVoiceSettings))
    return (result or 0) > 0
