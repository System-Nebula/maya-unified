"""Operator auth + user-management routes for the Maya Unified dashboard."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth.deps import require_admin, require_operator, resolve_operator_from_token
from services.auth.operator_store import (
    VALID_ROLES,
    any_operators_exist,
    create_operator,
    delete_operator,
    get_by_id,
    get_by_username,
    get_db_session,
    list_operators,
    touch_last_login,
    update_operator,
    validate_password,
    validate_role,
    verify_password,
)
from services.auth.session import (
    OPERATOR_SESSION_COOKIE,
    OPERATOR_SESSION_MAX_AGE,
    session_cookie_secure,
    sign_operator_session,
    verify_operator_session,
)

router = APIRouter(tags=["operator-auth"])


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

@router.get("/api/auth/me")
async def me(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    maya_op_session: Annotated[str | None, Cookie(alias=OPERATOR_SESSION_COOKIE)] = None,
):
    """Return current operator info, or setup_required flag if no operators exist."""
    no_ops = not await any_operators_exist(session)
    if no_ops:
        return {"ok": True, "setup_required": True}

    if not maya_op_session:
        return {"ok": False, "authenticated": False}

    payload = verify_operator_session(maya_op_session)
    if not payload:
        return {"ok": False, "authenticated": False}

    op = await get_by_id(session, payload.get("operator_id", ""))
    if op is None:
        return {"ok": False, "authenticated": False}

    return {
        "ok": True,
        "authenticated": True,
        "id": str(op.id),
        "username": op.username,
        "display_name": op.display_name,
        "role": op.role,
        "avatar_color": op.avatar_color,
        "is_banned": bool(getattr(op, "is_banned", False)),
    }


@router.post("/api/auth/login")
async def login(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
):
    from services.auth.login_throttle import (
        check_login_allowed,
        clear_login_failures,
        record_login_failure,
    )

    body = await request.json()
    username = (body.get("username") or "").strip().lower()
    password = body.get("password") or ""
    client_ip = request.client.host if request.client else "unknown"

    if not username or not password:
        raise HTTPException(status_code=400, detail="username and password required")

    if not check_login_allowed(client_ip, username):
        # Uniform message — do not reveal whether the username exists.
        raise HTTPException(status_code=401, detail="invalid username or password")

    op = await get_by_username(session, username)
    if op is None or not verify_password(op.password_hash, password):
        record_login_failure(client_ip, username)
        raise HTTPException(status_code=401, detail="invalid username or password")
    if getattr(op, "is_banned", False):
        raise HTTPException(status_code=403, detail="account banned")

    clear_login_failures(client_ip, username)
    await touch_last_login(session, op.id)
    from services.operator_voice.context import ensure_operator_seeded

    await ensure_operator_seeded(session, op.id)
    await session.commit()
    token = sign_operator_session(str(op.id))

    response.set_cookie(
        OPERATOR_SESSION_COOKIE,
        token,
        max_age=OPERATOR_SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=session_cookie_secure(),
    )
    return {
        "ok": True,
        "id": str(op.id),
        "username": op.username,
        "display_name": op.display_name,
        "role": op.role,
        "avatar_color": op.avatar_color,
    }


@router.post("/api/auth/logout")
async def logout(response: Response):
    response.delete_cookie(OPERATOR_SESSION_COOKIE)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Operator management (admin-only CRUD + self-edit)
# ---------------------------------------------------------------------------

def _op_dict(op) -> dict:
    return {
        "id": str(op.id),
        "username": op.username,
        "display_name": op.display_name,
        "role": op.role,
        "avatar_color": op.avatar_color,
        "is_banned": bool(getattr(op, "is_banned", False)),
        "created_at": op.created_at.isoformat() if op.created_at else None,
        "last_login": op.last_login.isoformat() if op.last_login else None,
    }


@router.get("/api/operators")
async def list_ops(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin=Depends(require_admin),
):
    ops = await list_operators(session)
    return {"ok": True, "operators": [_op_dict(o) for o in ops]}


@router.post("/api/operators")
async def create_op(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Create operator. Open only when no operators exist (first-run setup).
    Otherwise requires admin session.
    """
    body = await request.json()
    no_ops = not await any_operators_exist(session)

    if not no_ops:
        maya_op_session = request.cookies.get(OPERATOR_SESSION_COOKIE)
        current = await resolve_operator_from_token(session, maya_op_session)
        if current is None or current.role != "admin":
            raise HTTPException(
                status_code=403 if current else 401,
                detail="admin role required" if current else "not authenticated",
            )

    username = (body.get("username") or "").strip().lower()
    display_name = (body.get("display_name") or username).strip()
    password = body.get("password") or ""
    role = body.get("role", "operator" if not no_ops else "admin")

    if not username or not password:
        raise HTTPException(status_code=400, detail="username and password required")
    if len(username) < 2:
        raise HTTPException(status_code=400, detail="username must be at least 2 characters")

    try:
        validate_password(password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="role must be admin or operator")

    existing = await get_by_username(session, username)
    if existing is not None:
        raise HTTPException(status_code=409, detail="username already taken")

    if no_ops:
        role = "admin"

    op = await create_operator(
        session,
        username=username,
        display_name=display_name,
        password=password,
        role=role,
        avatar_color=body.get("avatar_color"),
    )
    from services.operator_voice.context import ensure_operator_seeded

    await ensure_operator_seeded(session, op.id)
    await session.commit()
    return {"ok": True, "operator": _op_dict(op)}


@router.patch("/api/operators/{operator_id}")
async def patch_op(
    operator_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current=Depends(require_operator),
):
    body = await request.json()
    is_admin = current.role == "admin"
    is_self = str(current.id) == operator_id

    if not is_admin and not is_self:
        raise HTTPException(status_code=403, detail="cannot edit another operator")

    if "role" in body and not is_admin:
        raise HTTPException(status_code=403, detail="only admins can change roles")

    if "role" in body and body["role"] not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="role must be admin or operator")

    if body.get("password"):
        try:
            validate_password(body["password"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    banned = body.get("is_banned") if is_admin else None

    try:
        op = await update_operator(
            session,
            operator_id,
            display_name=body.get("display_name"),
            role=body.get("role") if is_admin else None,
            avatar_color=body.get("avatar_color"),
            password=body.get("password"),
        )
        if banned is not None and is_admin:
            from services.auth.operator_store import set_operator_banned

            op = await set_operator_banned(session, operator_id, banned=bool(banned))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await session.commit()
    return {"ok": True, "operator": _op_dict(op)}


@router.delete("/api/operators/{operator_id}")
async def delete_op(
    operator_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin=Depends(require_admin),
    current=Depends(require_operator),
):
    if str(current.id) == operator_id:
        raise HTTPException(status_code=400, detail="cannot delete your own account")
    try:
        await delete_operator(session, operator_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return {"ok": True}
