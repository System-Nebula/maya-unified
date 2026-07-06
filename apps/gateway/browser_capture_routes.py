"""Browser capture HTTP routes."""

from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends

from maya_contracts import CaptureEvent, CaptureManifest
from maya_db.models.operator import OperatorUser
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth.deps import require_browser_capture
from services.auth.operator_store import get_db_session
from services.browser.capture import process_capture

router = APIRouter(prefix="/api/browser", tags=["browser-capture"])


async def get_http_client() -> httpx.AsyncClient:
    client = httpx.AsyncClient()
    try:
        yield client
    finally:
        await client.aclose()


@router.post("/capture", response_model=CaptureManifest)
async def capture_page(
    event: CaptureEvent,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    operator: Annotated[OperatorUser | None, Depends(require_browser_capture)],
    http_client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
) -> CaptureManifest:
    return await process_capture(event, session, http_client, operator=operator)
