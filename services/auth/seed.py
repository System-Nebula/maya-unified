"""Auto-seed a default operator — disabled by default (SEC-008).

First-run ownership uses POST /api/operators via /setup when the table is empty.
Set MAYA_SEED_DEFAULT_OPERATOR=1 only for explicit local bootstrap (unsafe).
"""

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


def seed_default_operator_enabled(environ: dict[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    return str(env.get("MAYA_SEED_DEFAULT_OPERATOR", "") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


async def seed_default_operator_if_needed(session: AsyncSession) -> bool:
    """Create default admin when explicitly enabled and table is empty."""
    if not seed_default_operator_enabled():
        return False
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
    log.warning(
        "seeded default operator %s via MAYA_SEED_DEFAULT_OPERATOR "
        "(change password immediately; prefer /setup first-run)",
        username,
    )
    return True
