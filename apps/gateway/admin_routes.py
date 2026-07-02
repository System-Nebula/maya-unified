"""Admin-only routes for cross-operator workspace management."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth.deps import require_admin
from services.auth.operator_store import (
    get_by_id,
    get_db_session,
    list_operators,
    set_operator_banned,
)
from services.operator_voice.paths import sync_personalities_file
from services.operator_voice.store import (
    clear_conversation,
    delete_personality_slug,
    get_or_create_personalities,
    list_conversation_messages,
    set_personality_flag,
    workspace_stats,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _op_summary(op, stats: dict) -> dict:
    return {
        "id": str(op.id),
        "username": op.username,
        "display_name": op.display_name,
        "role": op.role,
        "avatar_color": op.avatar_color,
        "is_banned": bool(getattr(op, "is_banned", False)),
        "created_at": op.created_at.isoformat() if op.created_at else None,
        "last_login": op.last_login.isoformat() if op.last_login else None,
        **stats,
    }


@router.get("/workspaces")
async def list_workspaces(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin=Depends(require_admin),
):
    ops = await list_operators(session)
    items = []
    for op in ops:
        stats = await workspace_stats(session, op.id)
        items.append(_op_summary(op, stats))
    return {"ok": True, "workspaces": items}


@router.get("/operators/{operator_id}/conversation")
async def get_operator_conversation(
    operator_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin=Depends(require_admin),
    limit: int = 100,
    offset: int = 0,
):
    op = await get_by_id(session, operator_id)
    if op is None:
        raise HTTPException(status_code=404, detail="operator not found")
    data = await list_conversation_messages(session, operator_id, limit=limit, offset=offset)
    return {"ok": True, "operator_id": operator_id, **data}


@router.delete("/operators/{operator_id}/conversation")
async def delete_operator_conversation(
    operator_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin=Depends(require_admin),
):
    op = await get_by_id(session, operator_id)
    if op is None:
        raise HTTPException(status_code=404, detail="operator not found")
    deleted = await clear_conversation(session, operator_id)
    await session.commit()
    return {"ok": True, "deleted_messages": deleted}


@router.get("/operators/{operator_id}/personalities")
async def get_operator_personalities(
    operator_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin=Depends(require_admin),
):
    op = await get_by_id(session, operator_id)
    if op is None:
        raise HTTPException(status_code=404, detail="operator not found")
    data = await get_or_create_personalities(session, operator_id)
    return {"ok": True, "operator_id": operator_id, **data}


@router.delete("/operators/{operator_id}/personalities/{slug}")
async def admin_delete_personality(
    operator_id: str,
    slug: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin=Depends(require_admin),
):
    op = await get_by_id(session, operator_id)
    if op is None:
        raise HTTPException(status_code=404, detail="operator not found")
    try:
        data = await delete_personality_slug(session, operator_id, slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    sync_personalities_file(operator_id, data["active"], data["personalities"])
    await session.commit()
    return {"ok": True, **data}


@router.post("/operators/{operator_id}/personalities/{slug}/flag")
async def admin_flag_personality(
    operator_id: str,
    slug: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin=Depends(require_admin),
):
    op = await get_by_id(session, operator_id)
    if op is None:
        raise HTTPException(status_code=404, detail="operator not found")
    body = await request.json()
    flagged = bool(body.get("flagged", True))
    try:
        data = await set_personality_flag(session, operator_id, slug, flagged=flagged)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    sync_personalities_file(operator_id, data["active"], data["personalities"])
    await session.commit()
    return {"ok": True, **data}


@router.post("/operators/{operator_id}/ban")
async def ban_operator(
    operator_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    admin=Depends(require_admin),
):
    if str(admin.id) == operator_id:
        raise HTTPException(status_code=400, detail="cannot ban your own account")
    try:
        op = await set_operator_banned(session, operator_id, banned=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return {"ok": True, "operator": _op_summary(op, await workspace_stats(session, op.id))}


@router.post("/operators/{operator_id}/unban")
async def unban_operator(
    operator_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin=Depends(require_admin),
):
    try:
        op = await set_operator_banned(session, operator_id, banned=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return {"ok": True, "operator": _op_summary(op, await workspace_stats(session, op.id))}
