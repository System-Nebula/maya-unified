"""Project parsed email knowledge into ontology nodes and notify followed operators."""

from __future__ import annotations

import json
import os
from typing import Any, Optional
from uuid import UUID

from maya_contracts import NotificationKind
from maya_db import (
    Follow as FollowDB,
    KnowledgeItem as KnowledgeItemDB,
    Notification as NotificationDB,
    Person as PersonDB,
)
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from maya_gateway.services.email_parse import ParsedEmail, slugify

from maya_graph.ontology_schema import ensure_ontology_schema


async def project_to_ontology(parsed: ParsedEmail) -> Optional[str]:
    dsn = os.getenv("MAYA_ONTOLOGY_DSN")
    if not dsn:
        return None
    try:
        import asyncpg
    except ImportError:
        return None

    conn = await asyncpg.connect(dsn)
    try:
        await ensure_ontology_schema(conn)
        artist_id = await conn.fetchval(
            """
            INSERT INTO ontology_node (domain, domain_id, node_type, label, slug, attrs)
            VALUES ('music', $1, 'artist', $2, $1, $3::jsonb)
            ON CONFLICT (domain, domain_id, node_type)
            DO UPDATE SET
              label = EXCLUDED.label,
              attrs = ontology_node.attrs || EXCLUDED.attrs,
              updated_at = now()
            RETURNING id
            """,
            parsed.artist_slug,
            parsed.artist_display,
            json.dumps(
                {
                    "brand_color": parsed.brand_color,
                    "visual_identity_source": "email",
                }
            ),
        )

        if parsed.album:
            release_id = slugify(parsed.album)
            await conn.execute(
                """
                INSERT INTO ontology_node (domain, domain_id, node_type, label, slug, attrs)
                VALUES ('music', $1, 'release', $2, $1, $3::jsonb)
                ON CONFLICT (domain, domain_id, node_type)
                DO UPDATE SET attrs = ontology_node.attrs || EXCLUDED.attrs, updated_at = now()
                """,
                f"{parsed.artist_slug}:{release_id}",
                parsed.album,
                json.dumps(
                    {
                        "release_date": parsed.release_date.isoformat()
                        if parsed.release_date
                        else None,
                        "promo": parsed.promo,
                        "handwritten_note": parsed.handwritten_note,
                    }
                ),
            )

        if parsed.track:
            track_slug = slugify(parsed.track)[:64]
            await conn.execute(
                """
                INSERT INTO ontology_node (domain, domain_id, node_type, label, slug, attrs)
                VALUES ('music', $1, 'track', $2, $1, $3::jsonb)
                ON CONFLICT (domain, domain_id, node_type)
                DO UPDATE SET attrs = ontology_node.attrs || EXCLUDED.attrs, updated_at = now()
                """,
                f"{parsed.artist_slug}:{track_slug}",
                parsed.track,
                json.dumps(parsed.extras),
            )

        source_id = await conn.fetchval(
            """
            INSERT INTO ontology_node (domain, domain_id, node_type, label, slug, attrs)
            VALUES ('operator', $1, 'source', $1, $1, $2::jsonb)
            ON CONFLICT (domain, domain_id, node_type)
            DO UPDATE SET updated_at = now()
            RETURNING id
            """,
            parsed.source,
            json.dumps({"kind": "email_newsletter"}),
        )
        if source_id and artist_id:
            await conn.execute(
                """
                INSERT INTO ontology_edge (source_id, target_id, edge_type, dimension, evidence)
                VALUES ($1, $2, 'visual_identity', 'semantic', $3::jsonb)
                ON CONFLICT (source_id, target_id, edge_type, dimension) DO NOTHING
                """,
                artist_id,
                source_id,
                json.dumps({"brand_color": parsed.brand_color}),
            )
        return str(artist_id)
    finally:
        await conn.close()


async def notify_followed_operators(
    session: AsyncSession,
    parsed: ParsedEmail,
    *,
    knowledge_item_id: UUID,
    artifact_url: str,
) -> list[str]:
    """Notify operators following this artist slug with notification_feed enabled."""
    follows = (
        await session.execute(
            select(FollowDB, PersonDB)
            .join(PersonDB, PersonDB.id == FollowDB.subject_id)
            .where(
                and_(
                    FollowDB.subject_type == "PERSON",
                    FollowDB.deleted_at.is_(None),
                    FollowDB.muted.is_(False),
                    FollowDB.notify_homepage.is_(True),
                    FollowDB.notification_feed.is_(True),
                    PersonDB.slug == parsed.artist_slug,
                )
            )
        )
    ).all()

    operator_ids = [f.operator_id for f, _ in follows]
    if not operator_ids:
        operator_ids = ["local"]

    for operator_id in dict.fromkeys(operator_ids):
        session.add(
            NotificationDB(
                kind=NotificationKind.ARTIST_NEWSLETTER.value,
                operator_id=operator_id,
                title=f"Update from {parsed.artist_display}",
                body=parsed.title,
                link=artifact_url,
                read=False,
            )
        )
    await session.flush()
    return list(dict.fromkeys(operator_ids))


async def save_knowledge_item(
    session: AsyncSession,
    parsed: ParsedEmail,
    *,
    artifact_key: str,
    operator_id: str = "local",
    ontology_artist_id: Optional[str] = None,
) -> KnowledgeItemDB:
    from datetime import datetime, timezone

    received = parsed.release_date or datetime.now(timezone.utc)
    row = KnowledgeItemDB(
        operator_id=operator_id,
        source=parsed.source,
        source_kind="email_newsletter",
        artist_slug=parsed.artist_slug,
        artist_display=parsed.artist_display,
        item_type=parsed.item_type.value,
        tags=parsed.tags,
        title=parsed.title,
        track=parsed.track,
        album=parsed.album,
        release_date=parsed.release_date,
        promo=parsed.promo,
        handwritten_note=parsed.handwritten_note,
        html_artifact_key=artifact_key,
        content_type="text/html; charset=utf-8",
        text_fallback=parsed.text_fallback,
        ontology_artist_id=UUID(ontology_artist_id) if ontology_artist_id else None,
        brand_color=parsed.brand_color,
        extras=parsed.extras,
        received_at=received,
    )
    session.add(row)
    await session.flush()
    return row
