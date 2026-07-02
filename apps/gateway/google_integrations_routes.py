"""Google integration routes — connect, status, disconnect, email/calendar services."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from maya_db.models.google_integration import GoogleConnection, OperatorGoogleIdentity
from maya_db.models.operator import OperatorUser

from services.auth.deps import require_operator
from services.auth.operator_store import get_db_session
from services.auth.session import OPERATOR_SESSION_COOKIE
from services.integrations.google.config import (
    APP_BASE_URL,
    GOOGLE_CONNECT_REDIRECT_URI,
    google_oauth_configured,
    redirect_uri_for_request,
)
from services.integrations.google.db_errors import raise_if_oauth_schema_missing
from services.integrations.google.oauth import (
    create_pkce_state,
    exchange_code,
    fetch_google_profile,
    pop_pkce_state,
)
from services.integrations.google.scopes import ALL_PERMISSION_GROUPS, connect_scopes
from services.integrations.google.service import (
    GoogleIntegrationError,
    connection_status,
    list_calendar_events,
    list_inbox_threads,
)
from services.integrations.google.token_store import delete_tokens, write_tokens

router = APIRouter(tags=["google-integrations"])


def _parse_permissions(raw: str | None) -> list[str]:
    if not raw:
        return ["mailbox_read", "calendar_read"]
    perms = [p.strip() for p in raw.split(",") if p.strip()]
    invalid = [p for p in perms if p not in ALL_PERMISSION_GROUPS]
    if invalid:
        raise HTTPException(status_code=400, detail=f"unknown permissions: {', '.join(invalid)}")
    return perms


@router.get("/api/integrations/google/status")
async def google_integration_status(
    op: Annotated[OperatorUser, Depends(require_operator)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
):
    return await connection_status(session, op.id)


@router.get("/api/integrations/google/connect")
async def google_connect(
    request: Request,
    op: Annotated[OperatorUser, Depends(require_operator)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    permissions: str | None = Query(None),
):
    if not google_oauth_configured():
        raise HTTPException(status_code=503, detail="Google OAuth not configured")
    perms = _parse_permissions(permissions)
    session_token = request.cookies.get(OPERATOR_SESSION_COOKIE)
    try:
        connect_redirect = redirect_uri_for_request(request, flow="connect")
        auth_url, _, _ = await create_pkce_state(
            session,
            flow="connect",
            requested_scopes=perms,
            operator_id=op.id,
            session_token=session_token,
            redirect_uri=connect_redirect,
        )
        await session.commit()
    except Exception as exc:
        raise_if_oauth_schema_missing(exc)
        raise
    return RedirectResponse(auth_url)


@router.get("/api/integrations/google/callback")
async def google_connect_callback(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        raise HTTPException(status_code=400, detail=f"Google OAuth error: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    pkce = await pop_pkce_state(session, state)
    if pkce is None or pkce.flow != "connect" or pkce.operator_id is None:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    perms = pkce.requested_scopes if isinstance(pkce.requested_scopes, list) else []
    if perms and all(isinstance(p, str) and p.startswith("https://") for p in perms):
        scopes = perms
    else:
        scopes = connect_scopes(perms if perms else None)

    try:
        creds = exchange_code(
            state=state,
            code=code,
            verifier=pkce.verifier,
            redirect_uri=pkce.redirect_uri or GOOGLE_CONNECT_REDIRECT_URI,
            scopes=scopes,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not creds.refresh_token:
        raise HTTPException(
            status_code=400,
            detail="No refresh token returned; revoke app access in Google Account and retry",
        )

    profile = fetch_google_profile(creds)
    operator_id = pkce.operator_id
    granted = list(creds.scopes or scopes)

    write_tokens(
        operator_id,
        {
            "refresh_token": creds.refresh_token,
            "google_sub": profile["google_sub"],
            "email": profile["email"],
            "scopes": granted,
        },
    )

    existing = await session.execute(
        select(GoogleConnection).where(GoogleConnection.operator_id == operator_id).limit(1)
    )
    conn = existing.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if conn:
        conn.google_sub = profile["google_sub"]
        conn.email = profile["email"]
        conn.scopes = granted
        conn.status = "active"
        conn.connected_at = now
    else:
        session.add(
            GoogleConnection(
                operator_id=operator_id,
                google_sub=profile["google_sub"],
                email=profile["email"],
                scopes=granted,
                status="active",
                connected_at=now,
            )
        )

    identity = await session.execute(
        select(OperatorGoogleIdentity).where(
            OperatorGoogleIdentity.google_sub == profile["google_sub"]
        )
    )
    ident = identity.scalar_one_or_none()
    if ident:
        ident.operator_id = operator_id
        ident.email = profile["email"]
    else:
        session.add(
            OperatorGoogleIdentity(
                operator_id=operator_id,
                google_sub=profile["google_sub"],
                email=profile["email"],
            )
        )

    await session.commit()
    return RedirectResponse(f"{APP_BASE_URL}/settings?tab=integrations")


@router.delete("/api/integrations/google")
async def google_disconnect(
    op: Annotated[OperatorUser, Depends(require_operator)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
):
    await session.execute(
        delete(GoogleConnection).where(GoogleConnection.operator_id == op.id)
    )
    delete_tokens(op.id)
    await session.commit()
    return {"ok": True, "connected": False}


@router.get("/api/services/email/inboxes")
async def email_inboxes(
    op: Annotated[OperatorUser, Depends(require_operator)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    max_results: int = Query(20, ge=1, le=100),
):
    try:
        return await list_inbox_threads(session, op.id, max_results=max_results)
    except GoogleIntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/services/calendar/events")
async def calendar_events(
    op: Annotated[OperatorUser, Depends(require_operator)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int = Query(50, ge=1, le=250),
):
    try:
        return await list_calendar_events(
            session,
            op.id,
            time_min=time_min,
            time_max=time_max,
            max_results=max_results,
        )
    except GoogleIntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
