"""OAuth database error helpers."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.exc import ProgrammingError


_MIGRATION_HINT = (
    "Google OAuth tables are missing. Run: "
    "cd packages/maya-db && DATABASE_URL=... python -m alembic upgrade head"
)


def raise_if_oauth_schema_missing(exc: BaseException) -> None:
    msg = str(getattr(exc, "orig", exc)).lower()
    if "oauth_pkce_states" in msg or "google_connections" in msg:
        raise HTTPException(status_code=503, detail=_MIGRATION_HINT) from exc
    if isinstance(exc, ProgrammingError) and "does not exist" in msg:
        raise HTTPException(status_code=503, detail=_MIGRATION_HINT) from exc
