"""Discover inbox — email webhook ingest and HTML artifact serving."""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from maya_contracts import KnowledgeItem, KnowledgeItemType
from maya_db import KnowledgeItem as KnowledgeItemDB, get_async_session
from sqlalchemy.ext.asyncio import AsyncSession

from maya_gateway.services.artifact_store import (
    artifact_public_url,
    load_html,
    store_html,
)
from maya_gateway.services.email_parse import parse_email_newsletter
from maya_gateway.services.music_projector import (
    notify_followed_operators,
    project_to_ontology,
    save_knowledge_item,
)

router = APIRouter(prefix="/api/discover", tags=["discover-inbox"])

DEFAULT_OPERATOR_ID = "local"
_WEBHOOK_SECRET = os.getenv("DISCOVER_INBOX_WEBHOOK_SECRET", "")


def _to_contract(row: KnowledgeItemDB) -> KnowledgeItem:
    artifact_id = row.html_artifact_key.split("/")[-1].replace(".html", "")
    return KnowledgeItem(
        id=str(row.id),
        source=row.source,
        source_kind=row.source_kind,
        artist_slug=row.artist_slug,
        artist_display=row.artist_display,
        type=KnowledgeItemType(row.item_type),
        tags=list(row.tags or []),
        title=row.title,
        track=row.track,
        album=row.album,
        release_date=row.release_date,
        promo=row.promo,
        handwritten_note=row.handwritten_note,
        html_artifact_key=row.html_artifact_key,
        html_artifact_url=artifact_public_url(artifact_id),
        text_fallback=row.text_fallback,
        ontology_artist_id=str(row.ontology_artist_id) if row.ontology_artist_id else None,
        brand_color=row.brand_color,
        received_at=row.received_at,
        extras=dict(row.extras or {}),
    )


def _verify_mailgun_signature(
    token: str | None,
    timestamp: str | None,
    signature: str | None,
) -> None:
    if not _WEBHOOK_SECRET:
        return
    if not token or not timestamp or not signature:
        raise HTTPException(status_code=401, detail="missing mailgun signature")
    digest = hmac.new(
        _WEBHOOK_SECRET.encode(),
        f"{timestamp}{token}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(digest, signature):
        raise HTTPException(status_code=401, detail="invalid mailgun signature")


@router.post("/inbox/webhook", response_model=KnowledgeItem)
async def inbox_webhook(
    request: Request,
    sender: str = Form("", alias="sender"),
    From: str = Form(""),  # noqa: N803
    subject: str = Form(""),
    body_html: str = Form("", alias="body-html"),
    body_plain: str = Form("", alias="body-plain"),
    Date: str = Form(""),  # noqa: N803
    timestamp: str | None = Form(None),
    token: str | None = Form(None),
    signature: str | None = Form(None),
    operator_id: str = DEFAULT_OPERATOR_ID,
    session: AsyncSession = Depends(get_async_session),
):
    _verify_mailgun_signature(token, timestamp, signature)
    from_header = From or sender
    html = body_html
    if not html:
        html = f"<html><body><pre>{body_plain}</pre></body></html>"

    parsed = parse_email_newsletter(
        from_header=from_header,
        subject=subject,
        html=html,
        text=body_plain or None,
        date_header=Date or None,
    )

    artifact_id, artifact_key = await store_html(html)
    ontology_id = await project_to_ontology(parsed)
    row = await save_knowledge_item(
        session,
        parsed,
        artifact_key=artifact_key,
        operator_id=operator_id,
        ontology_artist_id=ontology_id,
    )
    artifact_url = artifact_public_url(artifact_id)
    await notify_followed_operators(
        session,
        parsed,
        knowledge_item_id=row.id,
        artifact_url=artifact_url,
    )
    await session.commit()
    return _to_contract(row)


@router.get("/inbox/items/{item_id}", response_model=KnowledgeItem)
async def get_knowledge_item(
    item_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    row = await session.get(KnowledgeItemDB, UUID(item_id))
    if row is None:
        raise HTTPException(status_code=404, detail="knowledge item not found")
    return _to_contract(row)


@router.get("/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str) -> Response:
    loaded = load_html(artifact_id)
    if loaded is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    body, content_type = loaded
    return HTMLResponse(
        content=body.decode("utf-8", errors="replace"),
        media_type=content_type,
        headers={
            "Content-Security-Policy": "sandbox allow-scripts allow-same-origin",
            "X-Frame-Options": "SAMEORIGIN",
        },
    )
