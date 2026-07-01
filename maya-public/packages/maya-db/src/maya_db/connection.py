"""Async PostgreSQL connection management.

Prefer explicit DATABASE_URL-style configuration when available.
"""

from __future__ import annotations

import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


DEFAULT_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/maya_public"


def get_engine():
    """Create async engine from DATABASE_URL."""
    url = os.getenv("DATABASE_URL", DEFAULT_URL)
    return create_async_engine(url, echo=os.getenv("SQL_ECHO", "false").lower() == "true")


async_session_factory = async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session. Use as FastAPI dependency."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
