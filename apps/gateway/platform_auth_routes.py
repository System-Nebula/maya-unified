"""Platform OAuth — Google sign-in and provider status."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from maya_db.models.google_integration import OperatorGoogleIdentity
from maya_db.models.operator import OperatorUser

from services.auth.operator_store import get_by_username, get_db_session, touch_last_login
from services.auth.session import (
    OPERATOR_SESSION_COOKIE,
    OPERATOR_SESSION_MAX_AGE,
    session_cookie_secure,
    sign_operator_session,
)
from services.integrations.google.config import (
    APP_BASE_URL,
    GOOGLE_CLIENT_ID,
    GOOGLE_CONNECT_REDIRECT_URI,
    GOOGLE_LOGIN_REDIRECT_URI,
    dynamic_redirect_enabled,
    google_console_checklist,
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
from services.integrations.google.scopes import LOGIN_SCOPES

router = APIRouter(tags=["platform-auth"])

_SUPPORTED_PROVIDERS = ("google", "discord", "github")


@router.get("/api/platform/auth/status")
async def platform_auth_status():
    google_ok = google_oauth_configured()
    providers = ["google"] if google_ok else []
    payload: dict = {
        "oauth_available": google_ok,
        "providers": providers,
        "message": "" if google_ok else "Platform OAuth not configured in this deployment.",
    }
    if google_ok:
        checklist = google_console_checklist()
        payload["google"] = {
            "client_id": GOOGLE_CLIENT_ID,
            "login_redirect_uri": GOOGLE_LOGIN_REDIRECT_URI,
            "connect_redirect_uri": GOOGLE_CONNECT_REDIRECT_URI,
            "app_base_url": APP_BASE_URL,
            "dynamic_redirect": dynamic_redirect_enabled(),
            "console_checklist": checklist,
        }
    return payload


@router.get("/api/platform/auth/login/{provider}")
async def platform_oauth_login(
    request: Request,
    provider: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
):
    if provider not in _SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown OAuth provider")
    if provider == "discord":
        raise HTTPException(
            status_code=501,
            detail="Discord platform login is not configured yet.",
        )
    if provider != "google":
        raise HTTPException(status_code=501, detail=f"{provider} login not configured")
    if not google_oauth_configured():
        raise HTTPException(status_code=503, detail="Google OAuth not configured")

    try:
        login_redirect = redirect_uri_for_request(request, flow="login")
        auth_url, _, _ = await create_pkce_state(
            session,
            flow="login",
            requested_scopes=LOGIN_SCOPES,
            redirect_uri=login_redirect,
        )
        await session.commit()
    except Exception as exc:
        raise_if_oauth_schema_missing(exc)
        raise
    return RedirectResponse(auth_url)


@router.get("/api/platform/auth/callback/google")
async def platform_google_callback(
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
    if pkce is None or pkce.flow != "login":
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    try:
        creds = exchange_code(
            state=state,
            code=code,
            verifier=pkce.verifier,
            redirect_uri=pkce.redirect_uri or GOOGLE_LOGIN_REDIRECT_URI,
            scopes=LOGIN_SCOPES,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    profile = fetch_google_profile(creds)

    identity_result = await session.execute(
        select(OperatorGoogleIdentity).where(
            OperatorGoogleIdentity.google_sub == profile["google_sub"]
        )
    )
    identity = identity_result.scalar_one_or_none()

    operator: OperatorUser | None = None
    if identity:
        op_result = await session.execute(
            select(OperatorUser).where(OperatorUser.id == identity.operator_id)
        )
        operator = op_result.scalar_one_or_none()

    if operator is None:
        operator = await get_by_username(session, profile["email"])
        if operator is None:
            local = profile["email"].split("@")[0]
            operator = await get_by_username(session, local)

    if operator is None:
        raise HTTPException(
            status_code=403,
            detail="No linked operator account. Sign in with email first, then connect Google in Settings.",
        )

    if identity is None:
        session.add(
            OperatorGoogleIdentity(
                operator_id=operator.id,
                google_sub=profile["google_sub"],
                email=profile["email"],
            )
        )
    else:
        identity.email = profile["email"]

    await touch_last_login(session, operator.id)
    token = sign_operator_session(str(operator.id))
    await session.commit()

    redirect = RedirectResponse(url=f"{APP_BASE_URL}/")
    redirect.set_cookie(
        OPERATOR_SESSION_COOKIE,
        token,
        max_age=OPERATOR_SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=session_cookie_secure(),
    )
    return redirect


@router.get("/auth/google/callback", include_in_schema=False)
async def platform_google_callback_legacy(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """Legacy redirect URI path (Workspace-internal / prior Google Console config)."""
    return await platform_google_callback(
        session=session,
        code=code,
        state=state,
        error=error,
    )
