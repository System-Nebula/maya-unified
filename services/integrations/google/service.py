"""Google Gmail and Calendar integration services."""

from __future__ import annotations

import uuid
from typing import Any

from googleapiclient.discovery import build
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from maya_db.models.google_integration import GoogleConnection

from services.integrations.google.oauth import credentials_for_operator
from services.integrations.google.scopes import granted_permissions, has_permission


class GoogleIntegrationError(Exception):
    pass


async def get_active_connection(db: AsyncSession, operator_id: uuid.UUID) -> GoogleConnection:
    result = await db.execute(
        select(GoogleConnection).where(
            GoogleConnection.operator_id == operator_id,
            GoogleConnection.status == "active",
        )
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise GoogleIntegrationError("Google account not connected")
    return conn


def _gmail_service(operator_id: uuid.UUID):
    creds = credentials_for_operator(operator_id)
    if not creds:
        raise GoogleIntegrationError("Google credentials unavailable")
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _calendar_service(operator_id: uuid.UUID):
    creds = credentials_for_operator(operator_id)
    if not creds:
        raise GoogleIntegrationError("Google credentials unavailable")
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


async def connection_status(db: AsyncSession, operator_id: uuid.UUID) -> dict[str, Any]:
    result = await db.execute(
        select(GoogleConnection).where(GoogleConnection.operator_id == operator_id).limit(1)
    )
    conn = result.scalar_one_or_none()
    if not conn:
        return {
            "connected": False,
            "permissions": {p: False for p in granted_permissions([])},
        }
    perms = granted_permissions(list(conn.scopes or []))
    return {
        "connected": conn.status == "active",
        "email": conn.email,
        "status": conn.status,
        "scopes": list(conn.scopes or []),
        "permissions": perms,
        "connected_at": conn.connected_at.isoformat() if conn.connected_at else None,
    }


async def list_inbox_threads(
    db: AsyncSession,
    operator_id: uuid.UUID,
    *,
    max_results: int = 20,
) -> dict[str, Any]:
    conn = await get_active_connection(db, operator_id)
    if not has_permission(list(conn.scopes or []), "mailbox_read"):
        raise GoogleIntegrationError("mailbox_read permission not granted")
    gmail = _gmail_service(operator_id)
    resp = gmail.users().messages().list(
        userId="me", maxResults=max_results, labelIds=["INBOX"]
    ).execute()
    messages = resp.get("messages") or []
    threads: list[dict[str, Any]] = []
    for item in messages[:max_results]:
        msg = gmail.users().messages().get(
            userId="me", id=item["id"], format="metadata"
        ).execute()
        headers = {
            h["name"].lower(): h["value"]
            for h in msg.get("payload", {}).get("headers", [])
        }
        threads.append(
            {
                "id": item["id"],
                "thread_id": msg.get("threadId"),
                "subject": headers.get("subject"),
                "from": headers.get("from"),
                "snippet": msg.get("snippet"),
            }
        )
    return {"threads": threads, "count": len(threads)}


async def list_calendar_events(
    db: AsyncSession,
    operator_id: uuid.UUID,
    *,
    calendar_id: str = "primary",
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int = 50,
) -> dict[str, Any]:
    conn = await get_active_connection(db, operator_id)
    if not has_permission(list(conn.scopes or []), "calendar_read"):
        raise GoogleIntegrationError("calendar_read permission not granted")
    calendar = _calendar_service(operator_id)
    kwargs: dict[str, Any] = {
        "calendarId": calendar_id,
        "maxResults": max_results,
        "singleEvents": True,
        "orderBy": "startTime",
    }
    if time_min:
        kwargs["timeMin"] = time_min
    if time_max:
        kwargs["timeMax"] = time_max
    resp = calendar.events().list(**kwargs).execute()
    events = resp.get("items") or []
    return {
        "events": [
            {
                "id": e.get("id"),
                "summary": e.get("summary"),
                "start": e.get("start"),
                "end": e.get("end"),
                "html_link": e.get("htmlLink"),
            }
            for e in events
        ],
        "count": len(events),
    }
