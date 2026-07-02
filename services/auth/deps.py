"""FastAPI dependencies for operator session auth."""

from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from maya_db.models.operator import OperatorUser

from services.auth.operator_store import get_by_id, get_db_session
from services.auth.session import OPERATOR_SESSION_COOKIE, verify_operator_session


async def resolve_operator_from_token(
    session: AsyncSession,
    token: str | None,
) -> OperatorUser | None:
    if not token:
        return None
    payload = verify_operator_session(token)
    if not payload or "operator_id" not in payload:
        return None
    try:
        return await get_by_id(session, payload["operator_id"])
    except Exception:
        return None


async def resolve_operator(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OperatorUser | None:
    token = request.cookies.get(OPERATOR_SESSION_COOKIE)
    return await resolve_operator_from_token(session, token)


async def _get_operator(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    maya_op_session: Annotated[str | None, Cookie(alias=OPERATOR_SESSION_COOKIE)] = None,
) -> OperatorUser | None:
    if getattr(request.state, "operator", None) is not None:
        return request.state.operator
    op = await resolve_operator_from_token(session, maya_op_session)
    request.state.operator = op
    return op


async def require_operator(
    op: Annotated[OperatorUser | None, Depends(_get_operator)],
) -> OperatorUser:
    if op is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return op


async def require_admin(
    op: Annotated[OperatorUser, Depends(require_operator)],
) -> OperatorUser:
    if op.role != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return op
