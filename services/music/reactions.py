"""Music reaction persistence and graph projection."""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from maya_graph.music.primitives import DIM_SOCIAL, EDGE_REACTED, NODE_CANONICAL_WORK, NODE_DJ_SET
from maya_graph.projector import link, upsert_node
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = logging.getLogger(__name__)

VALID_REACTIONS = frozenset({"like", "star", "heart"})
VALID_ENTITY_TYPES = frozenset({"work", "set_entry", "set", "recording"})


async def set_reaction(
    *,
    operator_id: uuid.UUID,
    entity_type: str,
    entity_key: str,
    reaction: str,
    source_url: str | None = None,
    attrs: dict[str, Any] | None = None,
    active: bool = True,
) -> dict[str, Any]:
    entity_type = (entity_type or "").strip().lower()
    entity_key = (entity_key or "").strip()
    reaction = (reaction or "").strip().lower()
    if entity_type not in VALID_ENTITY_TYPES:
        raise ValueError(f"invalid entity_type: {entity_type!r}")
    if reaction not in VALID_REACTIONS:
        raise ValueError(f"invalid reaction: {reaction!r}")
    if not entity_key:
        raise ValueError("entity_key required")

    from maya_db.connection import async_session_factory
    from maya_db.models.music import MusicReaction

    async with async_session_factory() as session:
        if not active:
            await session.execute(
                delete(MusicReaction).where(
                    MusicReaction.operator_id == operator_id,
                    MusicReaction.entity_type == entity_type,
                    MusicReaction.entity_key == entity_key,
                    MusicReaction.reaction == reaction,
                )
            )
            await session.commit()
            return {"active": False, "entity_type": entity_type, "entity_key": entity_key, "reaction": reaction}

        stmt = (
            pg_insert(MusicReaction)
            .values(
                operator_id=operator_id,
                entity_type=entity_type,
                entity_key=entity_key,
                reaction=reaction,
                source_url=source_url,
                attrs=attrs or {},
            )
            .on_conflict_do_update(
                index_elements=["operator_id", "entity_type", "entity_key", "reaction"],
                set_={
                    "source_url": source_url,
                    "attrs": attrs or {},
                },
            )
            .returning(MusicReaction.id)
        )
        result = await session.execute(stmt)
        reaction_id = result.scalar_one()
        await session.commit()

    await _project_reaction_graph(
        operator_id=operator_id,
        entity_type=entity_type,
        entity_key=entity_key,
        reaction=reaction,
        attrs=attrs,
    )
    return {
        "id": str(reaction_id),
        "active": True,
        "entity_type": entity_type,
        "entity_key": entity_key,
        "reaction": reaction,
    }


async def list_reactions(
    *,
    entity_type: str | None = None,
    entity_key: str | None = None,
    operator_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    from maya_db.connection import async_session_factory
    from maya_db.models.music import MusicReaction

    async with async_session_factory() as session:
        q = select(MusicReaction)
        if entity_type:
            q = q.where(MusicReaction.entity_type == entity_type)
        if entity_key:
            q = q.where(MusicReaction.entity_key == entity_key)
        if operator_id:
            q = q.where(MusicReaction.operator_id == operator_id)
        rows = (await session.execute(q)).scalars().all()
        return [
            {
                "id": str(row.id),
                "operator_id": str(row.operator_id),
                "entity_type": row.entity_type,
                "entity_key": row.entity_key,
                "reaction": row.reaction,
                "source_url": row.source_url,
                "attrs": row.attrs,
            }
            for row in rows
        ]


async def _project_reaction_graph(
    *,
    operator_id: uuid.UUID,
    entity_type: str,
    entity_key: str,
    reaction: str,
    attrs: dict[str, Any] | None,
) -> None:
    dsn = os.getenv("MAYA_ONTOLOGY_DSN") or os.getenv("DATABASE_URL")
    if not dsn:
        return
    try:
        import asyncpg
    except ImportError:
        return

    node_type = NODE_DJ_SET if entity_type == "set" else NODE_CANONICAL_WORK
    domain_id = entity_key if entity_type in {"work", "set"} else entity_key.split(":", 1)[0]

    conn = await asyncpg.connect(dsn)
    try:
        operator_node = await upsert_node(
            conn,
            domain="operator",
            domain_id=str(operator_id),
            node_type="user",
            label=str(operator_id),
            slug=str(operator_id)[:8],
        )
        target_node = await upsert_node(
            conn,
            domain="music",
            domain_id=domain_id,
            node_type=node_type,
            label=entity_key,
            slug=entity_key.replace(":", "-")[:48],
        )
        await link(
            conn,
            operator_node,
            target_node,
            edge_type=EDGE_REACTED,
            dimension=DIM_SOCIAL,
            evidence={"reaction": reaction, "entity_type": entity_type, **(attrs or {})},
        )
    except Exception:
        logger.debug("reaction graph projection failed", exc_info=True)
    finally:
        await conn.close()
