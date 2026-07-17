"""Async CRUD operations for operator_users table."""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone

from maya_db import get_async_session
from maya_db.models.operator import OperatorUser
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth.passwords import hash_password, verify_password

VALID_ROLES = frozenset({"admin", "operator"})
_MIN_PASSWORD_LEN = 8

# Re-export for FastAPI Depends compatibility
get_db_session = get_async_session

__all__ = [
    "VALID_ROLES",
    "OperatorUser",
    "any_operators_exist",
    "count_admins",
    "create_operator",
    "delete_operator",
    "get_by_id",
    "get_by_username",
    "get_db_session",
    "hash_password",
    "list_operators",
    "set_operator_banned",
    "touch_last_login",
    "update_operator",
    "validate_password",
    "validate_role",
    "verify_password",
]

_AVATAR_COLOURS = [
    "#0a84ff", "#30d158", "#ff9f0a", "#ff453a",
    "#bf5af2", "#32ade6", "#ffd60a", "#ff6961",
    "#5e5ce6", "#64d2ff",
]


def validate_role(role: str) -> str:
    if role not in VALID_ROLES:
        raise ValueError(f"invalid role: {role!r}; must be admin or operator")
    return role


def validate_password(password: str) -> None:
    if len(password) < _MIN_PASSWORD_LEN:
        raise ValueError(f"password must be at least {_MIN_PASSWORD_LEN} characters")


def _pick_colour() -> str:
    return random.choice(_AVATAR_COLOURS)


async def any_operators_exist(session: AsyncSession) -> bool:
    result = await session.scalar(select(func.count()).select_from(OperatorUser))
    return (result or 0) > 0


async def count_admins(session: AsyncSession) -> int:
    result = await session.scalar(
        select(func.count()).select_from(OperatorUser).where(OperatorUser.role == "admin")
    )
    return result or 0


async def create_operator(
    session: AsyncSession,
    *,
    username: str,
    display_name: str,
    password: str,
    role: str = "operator",
    avatar_color: str | None = None,
    skip_password_validation: bool = False,
) -> OperatorUser:
    if not skip_password_validation:
        validate_password(password)
    role = validate_role(role)
    op = OperatorUser(
        username=username.strip().lower(),
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        role=role,
        avatar_color=avatar_color or _pick_colour(),
    )
    session.add(op)
    await session.flush()
    return op


async def get_by_username(session: AsyncSession, username: str) -> OperatorUser | None:
    return await session.scalar(
        select(OperatorUser).where(OperatorUser.username == username.strip().lower())
    )


async def get_by_id(session: AsyncSession, operator_id: str | uuid.UUID) -> OperatorUser | None:
    oid = uuid.UUID(str(operator_id)) if not isinstance(operator_id, uuid.UUID) else operator_id
    return await session.get(OperatorUser, oid)


async def list_operators(session: AsyncSession) -> list[OperatorUser]:
    result = await session.scalars(select(OperatorUser).order_by(OperatorUser.created_at))
    return list(result.all())


async def update_operator(
    session: AsyncSession,
    operator_id: str | uuid.UUID,
    *,
    display_name: str | None = None,
    role: str | None = None,
    avatar_color: str | None = None,
    password: str | None = None,
) -> OperatorUser:
    op = await get_by_id(session, operator_id)
    if op is None:
        raise ValueError(f"operator {operator_id} not found")
    if role is not None:
        validate_role(role)
        if op.role == "admin" and role != "admin":
            if await count_admins(session) <= 1:
                raise ValueError("cannot demote last admin")
        op.role = role
    if display_name is not None:
        op.display_name = display_name.strip()
    if avatar_color is not None:
        op.avatar_color = avatar_color
    if password is not None:
        validate_password(password)
        op.password_hash = hash_password(password)
        from services.auth.session_version import bump_session_version

        bump_session_version(str(op.id))
    await session.flush()
    return op


async def delete_operator(session: AsyncSession, operator_id: str | uuid.UUID) -> None:
    op = await get_by_id(session, operator_id)
    if op is None:
        raise ValueError(f"operator {operator_id} not found")
    if op.role == "admin" and await count_admins(session) <= 1:
        raise ValueError("cannot delete last admin")
    await session.delete(op)


async def set_operator_banned(
    session: AsyncSession,
    operator_id: str | uuid.UUID,
    *,
    banned: bool,
) -> OperatorUser:
    op = await get_by_id(session, operator_id)
    if op is None:
        raise ValueError(f"operator {operator_id} not found")
    if op.role == "admin" and banned:
        if await count_admins(session) <= 1:
            raise ValueError("cannot ban last admin")
    op.is_banned = banned
    from services.auth.session_version import bump_session_version

    bump_session_version(str(op.id))
    await session.flush()
    return op


async def touch_last_login(session: AsyncSession, operator_id: str | uuid.UUID) -> None:
    op = await get_by_id(session, operator_id)
    if op is not None:
        op.last_login = datetime.now(timezone.utc)
        await session.flush()
