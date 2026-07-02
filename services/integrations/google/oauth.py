"""Google OAuth flow helpers and PKCE state persistence."""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from oauthlib.oauth2.rfc6749.errors import OAuth2Error
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from maya_db.models.google_integration import OAuthPkceState

from services.integrations.google.config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_CONNECT_REDIRECT_URI,
    GOOGLE_LOGIN_REDIRECT_URI,
    google_oauth_configured,
)
from services.integrations.google.scopes import LOGIN_SCOPES, connect_scopes
from services.integrations.google.token_store import read_tokens

PKCE_TTL = timedelta(minutes=15)


def _generate_pkce_pair() -> tuple[str, str]:
    """Return (verifier, S256 challenge)."""
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _client_config(redirect_uri: str) -> dict:
    return {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }


def build_flow(*, scopes: list[str], redirect_uri: str, state: str | None = None) -> Flow:
    if not google_oauth_configured():
        raise RuntimeError("Google OAuth not configured")
    return Flow.from_client_config(
        _client_config(redirect_uri),
        scopes=scopes,
        state=state,
        redirect_uri=redirect_uri,
    )


async def create_pkce_state(
    db: AsyncSession,
    *,
    flow: str,
    requested_scopes: list[str],
    operator_id: uuid.UUID | None = None,
    session_token: str | None = None,
    redirect_uri: str | None = None,
) -> tuple[str, str, str]:
    """Return (auth_url, state, verifier)."""
    resolved_redirect = redirect_uri or (
        GOOGLE_LOGIN_REDIRECT_URI if flow == "login" else GOOGLE_CONNECT_REDIRECT_URI
    )
    if flow == "login":
        scopes = LOGIN_SCOPES
    else:
        scopes = connect_scopes(requested_scopes or None)
    oauth_flow = build_flow(scopes=scopes, redirect_uri=resolved_redirect)
    verifier, challenge = _generate_pkce_pair()
    auth_url, state = oauth_flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    expires_at = datetime.now(timezone.utc) + PKCE_TTL
    db.add(
        OAuthPkceState(
            state=state,
            verifier=verifier,
            flow=flow,
            requested_scopes=requested_scopes or scopes,
            operator_id=operator_id,
            session_token=session_token,
            redirect_uri=resolved_redirect,
            expires_at=expires_at,
        )
    )
    await db.flush()
    return auth_url, state, verifier


async def pop_pkce_state(db: AsyncSession, state: str) -> OAuthPkceState | None:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(OAuthPkceState).where(
            OAuthPkceState.state == state,
            OAuthPkceState.expires_at > now,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    await db.execute(delete(OAuthPkceState).where(OAuthPkceState.id == row.id))
    await db.flush()
    return row


def exchange_code(
    *,
    state: str,
    code: str,
    verifier: str,
    redirect_uri: str,
    scopes: list[str],
) -> Credentials:
    oauth_flow = build_flow(scopes=scopes, redirect_uri=redirect_uri, state=state)
    try:
        oauth_flow.fetch_token(code=code, code_verifier=verifier)
    except OAuth2Error as exc:
        raise RuntimeError(f"Google token exchange failed: {exc}") from exc
    creds = oauth_flow.credentials
    if not creds:
        raise RuntimeError("No credentials returned from Google")
    return creds


def fetch_google_profile(creds: Credentials) -> dict[str, str]:
    oauth2 = build("oauth2", "v2", credentials=creds, cache_discovery=False)
    profile = oauth2.userinfo().get().execute()
    google_sub = profile.get("id") or profile.get("sub") or ""
    email = profile.get("email") or ""
    if not google_sub or not email:
        raise RuntimeError("Could not read Google profile")
    return {"google_sub": google_sub, "email": email.lower()}


def credentials_for_operator(operator_id: uuid.UUID | str) -> Credentials | None:
    data = read_tokens(operator_id)
    if not data or not data.get("refresh_token"):
        return None
    if not google_oauth_configured():
        return None
    return Credentials(
        token=None,
        refresh_token=data["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=data.get("scopes") or [],
    )
