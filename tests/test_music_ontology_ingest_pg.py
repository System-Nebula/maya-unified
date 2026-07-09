"""Postgres-gated integration tests for DJ set ingest (env-gated)."""

from __future__ import annotations

import os
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import func, select, text

from helpers.music_set_fixtures import andrea_resolved_set
from maya_contracts import SourceRefModel
from maya_db.models.music import MusicPlatformLink, MusicTrack
from services.music.url_handler import PLATFORM_YOUTUBE, SetEntry

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping Postgres integration tests",
)


@pytest.fixture()
async def pg_session():
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        try:
            marker = await session.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'music_genre' AND column_name = 'beatport_id'"
                )
            )
            migrated = marker.scalar() is not None
        except Exception:  # noqa: BLE001
            migrated = False
        if not migrated:
            await engine.dispose()
            pytest.skip(
                "DATABASE_URL target lacks the maya-unified music schema "
                "(run alembic upgrade heads against it)"
            )
        yield session
    await engine.dispose()


def _test_resolved_set() -> object:
    """Minimal Andrea-shaped set with unique video id to avoid fixture collisions."""
    suffix = uuid.uuid4().hex[:10]
    video_id = f"test-{suffix}"
    resolved = andrea_resolved_set(video_id=video_id)
    # Seed work_keys on first two entries so graph contains_entry edges are written.
    entries: list[SetEntry] = []
    for i, entry in enumerate(resolved.entries):
        if i == 0:
            entry = SetEntry(
                position=entry.position,
                start_seconds=entry.start_seconds,
                end_seconds=entry.end_seconds,
                label=entry.label,
                artist=entry.artist,
                title=entry.title,
                work_key=f"fp:test-hard-bounce-{suffix}",
                source_refs=list(entry.source_refs),
            )
        elif i == 1:
            entry = SetEntry(
                position=entry.position,
                start_seconds=entry.start_seconds,
                end_seconds=entry.end_seconds,
                label=entry.label,
                artist=entry.artist,
                title=entry.title,
                work_key=f"fp:test-joann-{suffix}",
                source_refs=list(entry.source_refs)
                + [
                    SourceRefModel(
                        schema_id="wd",
                        external_id=f"Q-{suffix}",
                        confidence=0.85,
                    )
                ],
            )
        entries.append(entry)
    resolved.entries = entries
    return resolved


@pytest.mark.asyncio
async def test_ingest_set_persists_graph_and_relational_rows(pg_session) -> None:
    resolved = _test_resolved_set()
    set_key = resolved.set_key
    video_id = set_key.split(":", 1)[1]

    async def passthrough_enrich(r):
        return r

    with patch("services.music.set_ingest.enrich_set_entries", passthrough_enrich):
        from services.music.set_ingest import ingest_set

        await ingest_set(resolved)

    dj_set = await pg_session.execute(
        text(
            "SELECT id, node_type, domain_id FROM ontology_node "
            "WHERE domain = 'music' AND domain_id = :domain_id"
        ),
        {"domain_id": set_key},
    )
    dj_row = dj_set.mappings().first()
    assert dj_row is not None
    assert dj_row["node_type"] == "dj_set"

    edge_count = await pg_session.execute(
        text(
            "SELECT COUNT(*) FROM ontology_edge e "
            "JOIN ontology_node n ON n.id = e.src_node_id "
            "WHERE n.domain_id = :domain_id AND e.edge_type = 'contains_entry'"
        ),
        {"domain_id": set_key},
    )
    assert edge_count.scalar() == 2

    platform_links = await pg_session.execute(
        select(func.count())
        .select_from(MusicPlatformLink)
        .where(
            MusicPlatformLink.platform == PLATFORM_YOUTUBE,
            MusicPlatformLink.external_id.like(f"{video_id}#%"),
        )
    )
    assert platform_links.scalar() >= 26

    enriched_track = await pg_session.execute(
        select(MusicTrack).where(MusicTrack.canonical_work_key == resolved.entries[0].work_key)
    )
    track = enriched_track.scalar_one_or_none()
    assert track is not None
    assert track.enriched_at is not None

    # Cleanup graph + relational rows for this test set.
    await pg_session.execute(
        text(
            "DELETE FROM ontology_edge WHERE src_node_id = :node_id OR dst_node_id = :node_id"
        ),
        {"node_id": dj_row["id"]},
    )
    await pg_session.execute(
        text("DELETE FROM ontology_node WHERE domain_id = :domain_id"),
        {"domain_id": set_key},
    )
    for entry in resolved.entries[:2]:
        await pg_session.execute(
            text("DELETE FROM ontology_node WHERE domain_id = :domain_id"),
            {"domain_id": entry.work_key},
        )
    await pg_session.execute(
        text(
            "DELETE FROM music_platform_link WHERE platform = :platform "
            "AND external_id LIKE :pattern"
        ),
        {"platform": PLATFORM_YOUTUBE, "pattern": f"{video_id}#%"},
    )
    await pg_session.commit()


@pytest.mark.asyncio
async def test_set_reaction_persists_fred_again_set_entry(pg_session) -> None:
    from helpers.music_set_fixtures import FRED_AGAIN_SET_KEY, FRED_AGAIN_YT_URL, fred_again_reaction_payload
    from maya_db.models.music import MusicReaction
    from services.music.reactions import set_reaction

    try:
        marker = await pg_session.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'music_reaction'"
            )
        )
        if marker.scalar() is None:
            pytest.skip("music_reaction table not migrated")
    except Exception:  # noqa: BLE001
        pytest.skip("music_reaction table not available")

    operator_id = uuid.uuid4()
    payload = fred_again_reaction_payload(position=2)
    result = await set_reaction(
        operator_id=operator_id,
        entity_type=payload["entity_type"],
        entity_key=payload["entity_key"],
        reaction=payload["reaction"],
        source_url=payload["source_url"],
        attrs=payload["attrs"],
    )
    assert result["active"] is True
    assert result["entity_key"] == f"{FRED_AGAIN_SET_KEY}:2"

    row = await pg_session.execute(
        select(MusicReaction).where(
            MusicReaction.operator_id == operator_id,
            MusicReaction.entity_key == f"{FRED_AGAIN_SET_KEY}:2",
        )
    )
    reaction = row.scalar_one_or_none()
    assert reaction is not None
    assert reaction.entity_type == "set_entry"
    assert reaction.source_url == FRED_AGAIN_YT_URL
    assert reaction.attrs.get("timestamp_seconds") == 312

    await pg_session.execute(
        text("DELETE FROM music_reaction WHERE operator_id = :oid"),
        {"oid": operator_id},
    )
    await pg_session.commit()
