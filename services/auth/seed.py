"""Auto-seed a default operator when the table is empty."""

from __future__ import annotations

import logging
import os

from sqlalchemy.ext.asyncio import AsyncSession

from services.auth.operator_store import any_operators_exist, create_operator

log = logging.getLogger("maya-unified.auth.seed")

DEFAULT_OPERATOR_USERNAME = "admin"
DEFAULT_OPERATOR_PASSWORD = "admin"
DEFAULT_OPERATOR_DISPLAY = "Admin"


def default_username() -> str:
    return os.getenv("OPERATOR_DEFAULT_USERNAME", DEFAULT_OPERATOR_USERNAME).strip().lower()


def default_password() -> str:
    return os.getenv("OPERATOR_DEFAULT_PASSWORD", DEFAULT_OPERATOR_PASSWORD)


def default_display_name() -> str:
    return os.getenv("OPERATOR_DEFAULT_DISPLAY", DEFAULT_OPERATOR_DISPLAY).strip()


async def seed_default_operator_if_needed(session: AsyncSession) -> bool:
    """Create default admin when operator_users is empty. Returns True if seeded."""
    if await any_operators_exist(session):
        return False

    username = default_username()
    await create_operator(
        session,
        username=username,
        display_name=default_display_name(),
        password=default_password(),
        role="admin",
        skip_password_validation=True,
    )
    log.info(
        "seeded default operator %s (change password in Settings → Account)",
        username,
    )
    return True
