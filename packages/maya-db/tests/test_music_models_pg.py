"""Integration tests for music ontology relational models (env-gated)."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping Postgres integration tests",
)


@pytest.fixture()
async def pg_session():
    # Function-scoped with its own NullPool engine: pytest-asyncio (auto mode)
    # runs each test on a fresh event loop, and asyncpg connections/pools are
    # loop-bound — sharing the module-level engine across tests breaks with
    # "another operation is in progress".
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        # Guard: the target DB must carry the maya-unified music schema
        # (20260707_music_ontology). A legacy/other DB may own same-named
        # tables with a different shape — skip loudly rather than fail.
        try:
            marker = await session.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'music_genre' AND column_name = 'beatport_id'"
                )
            )
            migrated = marker.scalar() is not None
        except Exception:  # noqa: BLE001 — unreachable DB counts as unmigrated
            migrated = False
        if not migrated:
            await engine.dispose()
            pytest.skip(
                "DATABASE_URL target lacks the maya-unified music schema "
                "(run alembic upgrade heads against it, or it may be a "
                "legacy DB with colliding music_* tables)"
            )
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_music_genre_round_trip(pg_session) -> None:
    from maya_db.models.music import MusicGenre

    slug = f"test-genre-{uuid.uuid4().hex[:8]}"
    genre = MusicGenre(name="Test Genre", slug=slug)
    pg_session.add(genre)
    await pg_session.flush()
    assert genre.id is not None


@pytest.mark.asyncio
async def test_fingerprint_unique_violation(pg_session) -> None:
    from maya_db.models.music import MusicTrack

    fp = f"test::{uuid.uuid4().hex}"
    t1 = MusicTrack(title="A", canonical_fingerprint=fp)
    t2 = MusicTrack(title="B", canonical_fingerprint=fp)
    pg_session.add(t1)
    await pg_session.flush()
    pg_session.add(t2)
    with pytest.raises(Exception):
        await pg_session.flush()
    await pg_session.rollback()


@pytest.mark.asyncio
async def test_ontology_tables_exist_after_migration(pg_session) -> None:
    for table in ("ontology_node", "ontology_edge", "music_track", "music_platform_link"):
        result = await pg_session.execute(
            text("SELECT to_regclass(:name)"), {"name": f"public.{table}"}
        )
        assert result.scalar() is not None, f"missing table {table}"
