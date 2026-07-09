"""Ingest correlated DJ sets into the ontology graph and relational tier."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from maya_graph.artist_bridge import slugify
from maya_graph.music.primitives import (
    DIM_SEMANTIC,
    EDGE_CONTAINS_ENTRY,
    EDGE_HAS_RECORDING,
    EDGE_LINKED_SET,
    NODE_CANONICAL_WORK,
    NODE_DJ_SET,
    NODE_RECORDING,
)
from maya_graph.projector import link, upsert_node

from services.music.set_types import ResolvedSet, SetEntry

logger = logging.getLogger(__name__)


def _ontology_configured() -> bool:
    return bool(os.getenv("MAYA_ONTOLOGY_DSN") or os.getenv("DATABASE_URL"))


async def _enrich_entry_work_key(entry: SetEntry) -> SetEntry:
    if entry.work_key:
        return entry
    query = entry.label
    if entry.artist and entry.title:
        query = f"{entry.artist} - {entry.title}"
    try:
        from services.music.ontology import lookup

        meta = await lookup(query)
    except Exception:
        logger.debug("set entry lookup failed for %r", query, exc_info=True)
        return entry
    if meta is None or not meta.work_key:
        return entry
    entry.work_key = meta.work_key
    if meta.source_refs:
        seen = {(r.schema_id, r.external_id) for r in entry.source_refs}
        for ref in meta.source_refs:
            key = (ref.schema_id, ref.external_id)
            if key not in seen:
                seen.add(key)
                entry.source_refs.append(ref)
    return entry


async def enrich_set_entries(resolved: ResolvedSet) -> ResolvedSet:
    entries = [await _enrich_entry_work_key(entry) for entry in resolved.entries]
    return ResolvedSet(
        set_key=resolved.set_key,
        title=resolved.title,
        container_url=resolved.container_url,
        container_schema=resolved.container_schema,
        entries=entries,
        linked_sets=resolved.linked_sets,
        attrs=resolved.attrs,
    )


async def ingest_set(resolved: ResolvedSet) -> None:
    if not _ontology_configured():
        return

    enriched = await enrich_set_entries(resolved)
    schema, _, external_id = enriched.set_key.partition(":")
    if not external_id:
        return

    try:
        import asyncpg
    except ImportError:
        return

    dsn = os.getenv("MAYA_ONTOLOGY_DSN") or os.getenv("DATABASE_URL")
    if not dsn:
        return

    conn = await asyncpg.connect(dsn)
    try:
        set_node_id = await upsert_node(
            conn,
            domain="music",
            domain_id=enriched.set_key,
            node_type=NODE_DJ_SET,
            label=enriched.title,
            slug=external_id[:32],
            description=enriched.container_url,
            attrs={
                "container_schema": enriched.container_schema,
                "container_url": enriched.container_url,
                "entry_count": len(enriched.entries),
                **enriched.attrs,
            },
        )

        recording_node_ids: dict[str, str] = {}

        for entry in enriched.entries:
            work_node_id = None
            if entry.work_key:
                work_node_id = await upsert_node(
                    conn,
                    domain="music",
                    domain_id=entry.work_key,
                    node_type=NODE_CANONICAL_WORK,
                    label=entry.title or entry.label,
                    slug=entry.work_key.replace(":", "-")[:48],
                    attrs={"artist": entry.artist},
                )
                await link(
                    conn,
                    set_node_id,
                    work_node_id,
                    edge_type=EDGE_CONTAINS_ENTRY,
                    dimension=DIM_SEMANTIC,
                    evidence={
                        "position": entry.position,
                        "start_seconds": entry.start_seconds,
                        "end_seconds": entry.end_seconds,
                        "label": entry.label,
                    },
                )

            for ref in entry.source_refs:
                rec_domain_id = f"{ref.schema_id}:{ref.external_id}"
                rec_node_id = await upsert_node(
                    conn,
                    domain="music",
                    domain_id=rec_domain_id,
                    node_type=NODE_RECORDING,
                    label=entry.label,
                    slug=ref.external_id[:32],
                    description=ref.url,
                    attrs={
                        "platform": ref.schema_id,
                        "external_id": ref.external_id,
                        "set_position": entry.position,
                    },
                )
                recording_node_ids[rec_domain_id] = rec_node_id
                if work_node_id:
                    await link(
                        conn,
                        work_node_id,
                        rec_node_id,
                        edge_type=EDGE_HAS_RECORDING,
                        dimension=DIM_SEMANTIC,
                        evidence={"confidence": ref.confidence},
                    )

        for ref in enriched.linked_sets:
            linked_key = f"{ref.schema_id}:{ref.external_id}"
            linked_node_id = await upsert_node(
                conn,
                domain="music",
                domain_id=linked_key,
                node_type=NODE_DJ_SET,
                label=ref.url or linked_key,
                slug=ref.external_id[:32],
                description=ref.url,
                attrs={"linked": True},
            )
            await link(
                conn,
                set_node_id,
                linked_node_id,
                edge_type=EDGE_LINKED_SET,
                dimension=DIM_SEMANTIC,
                evidence={"url": ref.url},
            )

        await _persist_relational(enriched, recording_node_ids=recording_node_ids)
    finally:
        await conn.close()


async def _persist_relational(
    resolved: ResolvedSet,
    *,
    recording_node_ids: dict[str, str] | None = None,
) -> None:
    from maya_db.connection import async_session_factory
    from maya_db.models.music import MusicArtist, MusicPlatformLink, MusicTrack
    from maya_graph.music.primitives import canonical_fingerprint, work_key_from_fingerprint
    from sqlalchemy import func, select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    schema, _, set_external_id = resolved.set_key.partition(":")
    async with async_session_factory() as session:
        for entry in resolved.entries:
            artist_name = entry.artist
            title = entry.title or entry.label
            fp = canonical_fingerprint(artist_name or "", title)
            work_key = entry.work_key or work_key_from_fingerprint(fp)

            artist_id = None
            if artist_name:
                result = await session.execute(
                    select(MusicArtist).where(func.lower(MusicArtist.name) == artist_name.lower())
                )
                artist = result.scalar_one_or_none()
                if artist is None:
                    artist = MusicArtist(name=artist_name, sort_name=artist_name)
                    session.add(artist)
                    await session.flush()
                artist_id = artist.id

            track_stmt = (
                pg_insert(MusicTrack)
                .values(
                    title=title,
                    canonical_fingerprint=fp,
                    canonical_work_key=work_key if entry.work_key else None,
                    primary_artist_id=artist_id,
                    enriched_at=datetime.now(timezone.utc) if entry.work_key else None,
                )
                .on_conflict_do_update(
                    index_elements=["canonical_fingerprint"],
                    set_={
                        "canonical_work_key": work_key if entry.work_key else MusicTrack.canonical_work_key,
                        "enriched_at": datetime.now(timezone.utc) if entry.work_key else MusicTrack.enriched_at,
                    },
                )
                .returning(MusicTrack.id)
            )
            track_result = await session.execute(track_stmt)
            track_id = track_result.scalar_one()

            for ref in entry.source_refs:
                rec_domain_id = f"{ref.schema_id}:{ref.external_id}"
                graph_node_id = (recording_node_ids or {}).get(rec_domain_id)
                link_attrs: dict = {}
                if graph_node_id:
                    link_attrs["graph_node_id"] = graph_node_id
                link_stmt = (
                    pg_insert(MusicPlatformLink)
                    .values(
                        entity_type="track",
                        entity_id=track_id,
                        platform=ref.schema_id,
                        external_id=ref.external_id,
                        url=ref.url or resolved.container_url,
                        confidence=ref.confidence,
                        source="set_ingest",
                        attrs=link_attrs,
                    )
                    .on_conflict_do_nothing(
                        index_elements=["entity_type", "entity_id", "platform", "external_id"]
                    )
                )
                await session.execute(link_stmt)

            set_link_stmt = (
                pg_insert(MusicPlatformLink)
                .values(
                    entity_type="track",
                    entity_id=track_id,
                    platform=schema,
                    external_id=f"{set_external_id}#{entry.position}",
                    url=resolved.container_url,
                    confidence=0.95,
                    source="set_ingest",
                    attrs={
                        "set_key": resolved.set_key,
                        "position": entry.position,
                        "start_seconds": entry.start_seconds,
                    },
                )
                .on_conflict_do_nothing(
                    index_elements=["entity_type", "entity_id", "platform", "external_id"]
                )
            )
            await session.execute(set_link_stmt)

        await session.commit()
