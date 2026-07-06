"""Dual emit: Postgres outbox + Valkey stream."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from maya_contracts import BrowserCaptureGraphEvent
from maya_db.models.capture import BrowserCaptureOutbox

from services.browser.config import VALKEY_MAXLEN, VALKEY_STREAM, VALKEY_URL

log = logging.getLogger(__name__)

_valkey_client: redis.Redis | None = None


async def get_valkey() -> redis.Redis:
    global _valkey_client
    if _valkey_client is None:
        _valkey_client = redis.from_url(VALKEY_URL, encoding="utf-8", decode_responses=True)
    return _valkey_client


async def insert_outbox(
    session: AsyncSession,
    capture_id: uuid.UUID,
    payload: BrowserCaptureGraphEvent,
) -> BrowserCaptureOutbox:
    row = BrowserCaptureOutbox(
        capture_id=capture_id,
        payload=payload.model_dump(mode="json"),
    )
    session.add(row)
    return row


async def emit_valkey(payload: dict[str, Any]) -> None:
    """Publish capture event to Valkey stream (best-effort)."""
    client = await get_valkey()
    flat = {k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) for k, v in payload.items()}
    try:
        await client.xadd(
            VALKEY_STREAM,
            flat,
            maxlen=VALKEY_MAXLEN,
            approximate=True,
        )
    except Exception as exc:
        log.warning("Valkey XADD failed (capture still durable in Postgres): %s", exc)


async def close_valkey() -> None:
    global _valkey_client
    if _valkey_client is not None:
        await _valkey_client.aclose()
        _valkey_client = None
