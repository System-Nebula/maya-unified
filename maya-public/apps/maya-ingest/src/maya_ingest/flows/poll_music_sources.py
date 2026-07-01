"""Poll music sources for followed ontology artists."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from maya_contracts import NotificationKind
from maya_db import (
    Follow as FollowDB,
    Notification as NotificationDB,
    Person as PersonDB,
    get_async_session,
)
from prefect import flow, get_run_logger, task
from sqlalchemy import and_, select

_WORKSPACE = Path(os.getenv("MAYA_WORKSPACE_ROOT", Path.home() / "Workspace"))
if str(_WORKSPACE) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE))


@flow(name="poll-music-sources")
async def poll_music_sources() -> int:
    """Poll Beatport/Discogs/Bandcamp for followed artists (best-effort)."""
    logger = get_run_logger()
    emitted = 0
    dsn = os.getenv("MAYA_ONTOLOGY_DSN")
    if not dsn:
        logger.warning("MAYA_ONTOLOGY_DSN not set — skipping music source poll")
        return 0

    from maya_graph.artist_bridge import list_followed_artist_slugs

    async for session in get_async_session():
        follows = (
            await session.execute(
                select(FollowDB).where(
                    and_(
                        FollowDB.subject_type == "PERSON",
                        FollowDB.deleted_at.is_(None),
                        FollowDB.muted.is_(False),
                    )
                )
            )
        ).scalars().all()
        person_ids = [f.subject_id for f in follows]
        if not person_ids:
            return 0
        persons = (
            await session.execute(
                select(PersonDB).where(PersonDB.id.in_(person_ids))
            )
        ).scalars().all()
        slugs = [p.slug for p in persons if p.slug]
        matches = await list_followed_artist_slugs(slugs, dsn=dsn)
        for match in matches:
            count = await _poll_artist(session, match.label, match.ontology_slug, dsn)
            emitted += count
        await session.commit()
    logger.info("music source poll emitted %d notifications", emitted)
    return emitted


@task
async def _poll_artist(session, artist_name: str, slug: str, dsn: str) -> int:
    """Best-effort Discogs search for new releases; upsert ontology + notify."""
    try:
        from lib.sources.discogs.adapter import DiscogsAdapter
    except ImportError:
        return 0

    adapter = DiscogsAdapter()
    try:
        results = await adapter.search_releases(artist=artist_name, title="", limit=3)
    except Exception:
        return 0
    if not results:
        return 0

    try:
        import asyncpg
    except ImportError:
        return 0

    emitted = 0
    conn = await asyncpg.connect(dsn)
    try:
        for result in results[:3]:
            release_date = getattr(result, "release_date", None) or datetime.now(
                timezone.utc
            ).date().isoformat()
            node_id = await conn.fetchval(
                """
                INSERT INTO ontology_node (domain, domain_id, node_type, label, slug, attrs)
                VALUES ('music', $1, 'release', $2, $3, $4::jsonb)
                ON CONFLICT (domain, domain_id, node_type)
                DO UPDATE SET
                  label = EXCLUDED.label,
                  attrs = ontology_node.attrs || EXCLUDED.attrs,
                  updated_at = now()
                RETURNING id
                """,
                f"{slug}:{getattr(result, 'release_id', result.title)}",
                result.title,
                slugify_release(result.title),
                json.dumps(
                    {
                        "artist": artist_name,
                        "artist_slug": slug,
                        "release_date": str(release_date),
                        "source": "discogs",
                        "url": getattr(result, "url", None),
                        "first_seen_at": datetime.now(timezone.utc).isoformat(),
                    }
                ),
            )
            follows = (
                await session.execute(
                    select(FollowDB.operator_id).where(
                        and_(
                            FollowDB.subject_type == "PERSON",
                            FollowDB.deleted_at.is_(None),
                            FollowDB.muted.is_(False),
                            FollowDB.notify_homepage.is_(True),
                        )
                    )
                )
            ).scalars().all()
            for operator_id in dict.fromkeys(follows):
                session.add(
                    NotificationDB(
                        kind=NotificationKind.ARTIST_RELEASE.value,
                        operator_id=operator_id,
                        title=f"New release: {result.title}",
                        body=artist_name,
                        link=getattr(result, "url", None),
                        read=False,
                    )
                )
                emitted += 1
            _ = node_id
    finally:
        await conn.close()
    return emitted


def slugify_release(title: str) -> str:
    import re

    slug = title.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")[:64]
