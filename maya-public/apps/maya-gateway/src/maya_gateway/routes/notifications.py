"""Persistent notification inbox + SSE push for the homepage."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from maya_contracts import (
    MarkReadRequest,
    Notification,
    NotificationKind,
    PaginatedResponse,
)
from maya_db import Notification as NotificationDB, get_async_session, get_engine
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    pass

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

_STREAM_POLL_SECONDS = 5.0


def _to_response(n: NotificationDB) -> Notification:
    return Notification(
        id=str(n.id),
        operator_id=n.operator_id,
        kind=NotificationKind(n.kind),
        channel_id=str(n.channel_id) if n.channel_id else None,
        video_id=str(n.video_id) if n.video_id else None,
        title=n.title,
        body=n.body,
        link=n.link,
        read=n.read,
        created_at=n.created_at,
    )


DEFAULT_OPERATOR_ID = "local"


@router.get("", response_model=PaginatedResponse[Notification])
async def list_notifications(
    limit: int = 50,
    offset: int = 0,
    read: Optional[bool] = None,
    operator_id: str = DEFAULT_OPERATOR_ID,
    session: AsyncSession = Depends(get_async_session),
):
    base = (
        select(NotificationDB)
        .where(NotificationDB.operator_id == operator_id)
        .order_by(NotificationDB.created_at.desc())
    )
    if read is not None:
        base = base.where(NotificationDB.read.is_(read))
    total = len((await session.execute(base)).scalars().all())
    rows = (await session.execute(base.limit(limit).offset(offset))).scalars().all()
    items = [_to_response(n) for n in rows]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.patch("/{notification_id}/read", response_model=Notification)
async def mark_read(
    notification_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    n = await session.get(NotificationDB, _uuid(notification_id))
    if n is None:
        raise HTTPException(status_code=404, detail="notification not found")
    n.read = True
    await session.flush()
    return _to_response(n)


@router.post("/mark-read", response_model=dict)
async def mark_many_read(
    req: MarkReadRequest,
    session: AsyncSession = Depends(get_async_session),
):
    ids = [_uuid(i) for i in req.ids]
    await session.execute(
        update(NotificationDB).where(NotificationDB.id.in_(ids)).values(read=True)
    )
    await session.flush()
    return {"marked": len(ids)}


@router.post("/mark-all-read", response_model=dict)
async def mark_all_read(
    operator_id: str = DEFAULT_OPERATOR_ID,
    session: AsyncSession = Depends(get_async_session),
):
    result = await session.execute(
        update(NotificationDB)
        .where(
            NotificationDB.read.is_(False),
            NotificationDB.operator_id == operator_id,
        )
        .values(read=True)
    )
    await session.flush()
    return {"marked": result.rowcount or 0}


@router.get("/stream")
async def stream() -> StreamingResponse:
    """Server-Sent Events: emits each new unread notification as it lands."""

    async def event_generator():
        engine = get_engine()
        last_seen = datetime.now(timezone.utc)
        yield f"event: hello\ndata: {json.dumps({'ts': last_seen.isoformat()})}\n\n"
        while True:
            await asyncio.sleep(_STREAM_POLL_SECONDS)
            async with AsyncSession(engine) as session:
                rows = (
                    await session.execute(
                        select(NotificationDB)
                        .where(
                            NotificationDB.created_at > last_seen,
                            NotificationDB.operator_id == DEFAULT_OPERATOR_ID,
                        )
                        .order_by(NotificationDB.created_at.asc())
                    )
                ).scalars().all()
            for row in rows:
                payload = _to_response(row).model_dump(mode="json")
                yield (
                    "event: notification\n"
                    f"data: {json.dumps(payload, default=str)}\n\n"
                )
                last_seen = row.created_at
            if not rows:
                yield f"event: heartbeat\ndata: {datetime.now(timezone.utc).isoformat()}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid uuid") from exc
