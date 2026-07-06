"""Browser capture orchestration — validate, store, emit, return manifest."""

from __future__ import annotations

import base64
import logging
import time
import uuid

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from maya_contracts import (
    BrowserCaptureGraphEvent,
    CaptureEvent,
    CaptureManifest,
    StoredAssetDescriptor,
)
from maya_db.models.capture import Capture
from maya_db.models.operator import OperatorUser

from services.browser.emitter import emit_valkey, insert_outbox
from services.browser.hashing import compute_content_hash
from services.browser.object_store import upload_capture_asset

log = logging.getLogger(__name__)


async def find_existing_capture(session: AsyncSession, content_hash: str) -> Capture | None:
    result = await session.execute(
        select(Capture).where(Capture.content_hash == content_hash).limit(1)
    )
    return result.scalar_one_or_none()


async def process_capture(
    event: CaptureEvent,
    session: AsyncSession,
    http_client: httpx.AsyncClient,
    operator: OperatorUser | None = None,
) -> CaptureManifest:
    content_hash = compute_content_hash(event)

    existing = await find_existing_capture(session, content_hash)
    if existing is not None:
        return CaptureManifest(
            capture_id=str(existing.capture_id),
            content_hash=content_hash,
            duplicate=True,
            stored_assets=[],
            queued_at=time.time(),
        )

    capture_id = uuid.uuid4()
    stored_assets: list[dict] = []

    try:
        for asset in event.assets:
            raw = base64.b64decode(asset.data_b64)
            desc = await upload_capture_asset(
                http_client,
                str(capture_id),
                asset.kind,
                raw,
                asset.mime_type,
            )
            stored_assets.append(desc)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"object store upload failed: {exc}") from exc

    row = Capture(
        capture_id=capture_id,
        content_hash=content_hash,
        capture_type=event.capture_type,
        url=event.url,
        title=event.title,
        reader_text=event.reader_text,
        selection=event.selection,
        tags=list(event.tags),
        metadata_=dict(event.metadata),
        assets=stored_assets,
        operator_id=operator.id if operator is not None else None,
        client_captured_at=event.client_captured_at,
    )
    session.add(row)

    graph_event = BrowserCaptureGraphEvent(
        capture_id=str(capture_id),
        content_hash=content_hash,
        capture_type=event.capture_type,
        url=event.url,
        title=event.title or "",
        reader_text=event.reader_text or "",
        selection=event.selection or "",
        tags=list(event.tags),
        metadata=dict(event.metadata),
        assets=stored_assets,
        operator_id=str(operator.id) if operator is not None else None,
    )
    await insert_outbox(session, capture_id, graph_event)
    await session.flush()

    await emit_valkey(graph_event.model_dump(mode="json"))

    return CaptureManifest(
        capture_id=str(capture_id),
        content_hash=content_hash,
        duplicate=False,
        stored_assets=[StoredAssetDescriptor.model_validate(a) for a in stored_assets],
        queued_at=time.time(),
    )
