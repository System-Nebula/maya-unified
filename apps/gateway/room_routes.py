"""Public multi-user voice room API."""

from __future__ import annotations

import json
import queue
from typing import Annotated

from fastapi import APIRouter, Body, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth.deps import require_operator
from services.auth.operator_store import get_db_session
from services.rooms.guest_session import (
    GUEST_SESSION_COOKIE,
    GUEST_SESSION_MAX_AGE,
    verify_guest_session,
)
from services.rooms import service as room_svc
from services.voice.hub import hub

router = APIRouter(prefix="/api/rooms", tags=["voice-rooms"])


def _room_snapshot(room) -> dict:
    from services.settings.public import to_public_settings

    return {
        "settings": to_public_settings(room.settings_snapshot or {}),
        "personality": room.personality_snapshot or {},
    }


@router.post("")
async def create_room(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    operator=Depends(require_operator),
):
    body = await request.json()
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    room = await room_svc.create_room(
        session,
        operator.id,
        name=name,
        description=str(body.get("description") or ""),
        visibility=str(body.get("visibility") or "private"),
        personality_slug=body.get("personality_slug"),
    )
    await session.commit()
    return {
        "ok": True,
        "room": {
            "id": str(room.id),
            "slug": room.slug,
            "name": room.name,
            "visibility": room.visibility,
            "status": room.status,
            "share_url": f"/room/{room.slug}",
        },
    }


@router.get("")
async def list_rooms(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    operator=Depends(require_operator),
):
    rooms = await room_svc.list_rooms_for_operator(session, operator.id)
    out = []
    for room in rooms:
        count = await room_svc.active_member_count(session, room.id)
        out.append(
            {
                "id": str(room.id),
                "slug": room.slug,
                "name": room.name,
                "visibility": room.visibility,
                "status": room.status,
                "member_count": count,
                "max_participants": room.max_participants,
                "is_owner": str(room.owner_operator_id) == str(operator.id),
                "share_url": f"/room/{room.slug}",
            }
        )
    return {"ok": True, "rooms": out}


@router.get("/{slug}")
async def room_info(slug: str, session: Annotated[AsyncSession, Depends(get_db_session)]):
    room = await room_svc.get_room_by_slug(session, slug)
    if room is None:
        raise HTTPException(404, "room not found")
    count = await room_svc.active_member_count(session, room.id)
    queue_state = await room_svc.get_queue_state(session, room.id)
    info = room_svc.room_availability(room, count)
    return {
        "ok": True,
        "room": {
            "slug": room.slug,
            "name": room.name,
            "description": room.description,
            "visibility": room.visibility,
            "status": room.status,
            **info,
            **queue_state,
        },
    }


@router.post("/{slug}/join")
async def join_room(
    slug: str,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    maya_guest_session: Annotated[str | None, Cookie(alias=GUEST_SESSION_COOKIE)] = None,
):
    room = await room_svc.get_room_by_slug(session, slug)
    if room is None:
        raise HTTPException(404, "room not found")
    body = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        pass
    op = getattr(request.state, "operator", None)
    if op is not None:
        member = await room_svc.join_room_operator(
            session, room, op.id, str(body.get("display_name") or op.display_name or op.username)
        )
        await session.commit()
        return {
            "ok": True,
            "member_id": str(member.id),
            "display_name": member.display_name,
            "role": member.role,
        }
    if room.visibility != "public":
        raise HTTPException(403, "login required for private room")
    display_name = str(body.get("display_name") or "Guest").strip()
    if not display_name:
        raise HTTPException(400, "display_name required")
    member, cookie = await room_svc.join_room_guest(session, room, display_name)
    await session.commit()
    response.set_cookie(
        GUEST_SESSION_COOKIE,
        cookie,
        max_age=GUEST_SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return {
        "ok": True,
        "member_id": str(member.id),
        "display_name": member.display_name,
        "role": member.role,
    }


async def _resolve_member(
    session: AsyncSession,
    room,
    request: Request,
    guest_cookie: str | None,
):
    op = getattr(request.state, "operator", None)
    if op is not None:
        member = await room_svc.join_room_operator(session, room, op.id, op.display_name or op.username)
        return member
    payload = verify_guest_session(guest_cookie)
    if not payload or str(payload.get("room_id")) != str(room.id):
        raise HTTPException(401, "not a room member")
    member = await room_svc.get_member(session, payload["member_id"])
    if member is None or member.left_at is not None:
        raise HTTPException(401, "not a room member")
    return member


@router.get("/{slug}/messages")
async def room_messages(
    slug: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    since_id: int = 0,
    maya_guest_session: Annotated[str | None, Cookie(alias=GUEST_SESSION_COOKIE)] = None,
):
    room = await room_svc.get_room_by_slug(session, slug)
    if room is None:
        raise HTTPException(404, "room not found")
    await _resolve_member(session, room, request, maya_guest_session)
    msgs = await room_svc.get_room_messages(session, room.id, since_id=since_id)
    return {"ok": True, "messages": msgs}


@router.post("/{slug}/chat")
async def room_chat(
    slug: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    data: dict = Body(...),
    maya_guest_session: Annotated[str | None, Cookie(alias=GUEST_SESSION_COOKIE)] = None,
):
    room = await room_svc.get_room_by_slug(session, slug)
    if room is None:
        raise HTTPException(404, "room not found")
    if room.status != "open":
        raise HTTPException(403, "room is closed")
    member = await _resolve_member(session, room, request, maya_guest_session)
    text = str((data or {}).get("text", "")).strip()
    if not text:
        raise HTTPException(400, "empty message")
    await room_svc.append_room_message(session, room.id, member.id, "user", f"{member.display_name}: {text}")
    history = await room_svc.room_history_messages(session, room.id)
    snapshot = _room_snapshot(room)
    result = hub.chat_in_room(
        str(room.id),
        text,
        member_name=member.display_name,
        history=history,
        snapshot=snapshot,
    )
    if result.get("ok") and result.get("text"):
        await room_svc.append_room_message(session, room.id, None, "assistant", result["text"])
    await session.commit()
    return result


@router.get("/{slug}/queue")
async def room_queue(
    slug: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    maya_guest_session: Annotated[str | None, Cookie(alias=GUEST_SESSION_COOKIE)] = None,
):
    room = await room_svc.get_room_by_slug(session, slug)
    if room is None:
        raise HTTPException(404, "room not found")
    await _resolve_member(session, room, request, maya_guest_session)
    state = await room_svc.get_queue_state(session, room.id)
    return {"ok": True, **state}


@router.post("/{slug}/queue/request")
async def queue_request(
    slug: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    maya_guest_session: Annotated[str | None, Cookie(alias=GUEST_SESSION_COOKIE)] = None,
):
    room = await room_svc.get_room_by_slug(session, slug)
    if room is None:
        raise HTTPException(404, "room not found")
    member = await _resolve_member(session, room, request, maya_guest_session)
    entry = await room_svc.request_speak(session, room.id, member.id)
    state = await room_svc.get_queue_state(session, room.id)
    if not state.get("active_speaker_id"):
        granted = await room_svc.grant_next_speaker(session, room.id)
        if granted and str(granted.member_id) == str(member.id):
            hub.start_room_voice(
                str(room.id),
                str(member.id),
                member.display_name,
                _room_snapshot(room),
            )
    await session.commit()
    state = await room_svc.get_queue_state(session, room.id)
    return {"ok": True, "entry_id": str(entry.id), **state}


@router.post("/{slug}/queue/release")
async def queue_release(
    slug: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    maya_guest_session: Annotated[str | None, Cookie(alias=GUEST_SESSION_COOKIE)] = None,
):
    room = await room_svc.get_room_by_slug(session, slug)
    if room is None:
        raise HTTPException(404, "room not found")
    member = await _resolve_member(session, room, request, maya_guest_session)
    await room_svc.release_speaker(session, room.id, member.id)
    hub.stop_room_voice(str(room.id), str(member.id))
    nxt = await room_svc.grant_next_speaker(session, room.id)
    if nxt:
        nxt_member = await room_svc.get_member(session, nxt.member_id)
        if nxt_member:
            hub.start_room_voice(
                str(room.id),
                str(nxt_member.id),
                nxt_member.display_name,
                _room_snapshot(room),
            )
    await session.commit()
    state = await room_svc.get_queue_state(session, room.id)
    return {"ok": True, **state}


@router.post("/{slug}/leave")
async def leave_room(
    slug: str,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    maya_guest_session: Annotated[str | None, Cookie(alias=GUEST_SESSION_COOKIE)] = None,
):
    room = await room_svc.get_room_by_slug(session, slug)
    if room is None:
        raise HTTPException(404, "room not found")
    member = await _resolve_member(session, room, request, maya_guest_session)
    await room_svc.leave_room(session, member.id)
    await session.commit()
    response.delete_cookie(GUEST_SESSION_COOKIE)
    return {"ok": True}


@router.patch("/{slug}")
async def patch_room(
    slug: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    operator=Depends(require_operator),
):
    room = await room_svc.get_room_by_slug(session, slug)
    if room is None:
        raise HTTPException(404, "room not found")
    if str(room.owner_operator_id) != str(operator.id):
        raise HTTPException(403, "owner only")
    body = await request.json()
    if "status" in body and body["status"] in ("open", "closed", "full"):
        room.status = body["status"]
    if "visibility" in body and body["visibility"] in ("public", "private"):
        room.visibility = body["visibility"]
    await session.commit()
    return {"ok": True, "status": room.status, "visibility": room.visibility}


@router.get("/{slug}/events")
async def room_events(
    slug: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    maya_guest_session: Annotated[str | None, Cookie(alias=GUEST_SESSION_COOKIE)] = None,
):
    room = await room_svc.get_room_by_slug(session, slug)
    if room is None:
        raise HTTPException(404, "room not found")
    await _resolve_member(session, room, request, maya_guest_session)
    room_id = str(room.id)
    q = hub.subscribe(room_id=room_id)

    def gen():
        try:
            while True:
                try:
                    event = q.get(timeout=15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    yield ": keep-alive\n\n"
        finally:
            hub.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream")
