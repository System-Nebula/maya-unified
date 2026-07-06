"""MusicQueryBroker — parameterized query broker for the music ontology.

Single entry point: normalizes a parameterized query (WorkQuery /
RecordingQuery) and brokers it across the property graph and registered
source schemas. Wikidata is one schema we build off; Discogs/SoundCloud/
Beatport are designed peers — the broker never special-cases a schema.

Graph access follows artist_bridge conventions: asyncpg, MAYA_ONTOLOGY_DSN
default, connect-per-operation (a shared pool is future work). All SQL is
parameterized ($n args) — values are never interpolated into SQL text.

Relational persistence deliberately lives OUTSIDE this package: the broker
emits ResolutionEvents through the optional ``on_resolution`` hook and the
platform layer (services/music/ontology.py) persists maya-db rows.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from rapidfuzz import fuzz, utils as fuzz_utils

from maya_graph.music.primitives import (
    DIM_SEMANTIC,
    DOMAIN,
    EDGE_HAS_RECORDING,
    EDGE_PERFORMED_BY,
    NODE_CANONICAL_WORK,
    NODE_RECORDING,
    CanonicalWork,
    Recording,
    RecordingQuery,
    ResolutionEvent,
    SourceRef,
    WorkCandidate,
    WorkQuery,
    work_key_from_fingerprint,
)
from maya_graph.music.schemas.base import SourceSchema
from maya_graph.projector import link, upsert_artist_node, upsert_node

logger = logging.getLogger(__name__)

GRAPH_SOURCE = "graph"  # ResolutionEvent.source_schema for graph cache hits


def _load_attrs(raw: Any) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    import json

    return json.loads(raw)


def _score(text: str, label: str, aliases: Sequence[str] = ()) -> float:
    """0..1 fuzzy confidence of a candidate label (or alias) vs query text."""
    ratio = lambda a, b: fuzz.token_set_ratio(a, b, processor=fuzz_utils.default_process)  # noqa: E731
    best = ratio(text, label)
    for alias in aliases:
        best = max(best, ratio(text, alias))
    return best / 100.0


def _work_from_row(row: Any) -> CanonicalWork:
    attrs = _load_attrs(row["attrs"])
    anchors = tuple(
        SourceRef(
            schema=a.get("schema", ""),
            external_id=a.get("external_id", ""),
            url=a.get("url"),
        )
        for a in attrs.get("anchors", [])
        if isinstance(a, dict)
    )
    return CanonicalWork(
        key=row["domain_id"],
        label=row["label"],
        aliases=tuple(attrs.get("aliases", []) or ()),
        anchors=anchors,
        attrs=attrs,
    )


def _recording_from_row(row: Any) -> Recording:
    attrs = _load_attrs(row["attrs"])
    return Recording(
        source=SourceRef.from_domain_key(row["domain_id"], url=attrs.get("url")),
        title=attrs.get("title") or row["label"],
        duration_seconds=attrs.get("duration_seconds"),
        webpage_url=attrs.get("webpage_url"),
        stream_url=attrs.get("stream_url"),
        attrs=attrs,
    )


class MusicQueryBroker:
    def __init__(
        self,
        *,
        dsn: str | None = None,
        schemas: Sequence[SourceSchema] = (),
        graph_budget_s: float = 0.4,
        schema_budget_s: float = 3.5,
        confidence_threshold: float = 0.6,
        on_resolution: Callable[[ResolutionEvent], Awaitable[None]] | None = None,
    ) -> None:
        self._dsn_override = dsn
        self.schemas = list(schemas)
        self.graph_budget_s = graph_budget_s
        self.schema_budget_s = schema_budget_s
        self.confidence_threshold = confidence_threshold
        self.on_resolution = on_resolution
        self._bg_tasks: set[asyncio.Task] = set()

    # -- connection ---------------------------------------------------------

    @property
    def _dsn(self) -> str | None:
        return self._dsn_override or os.getenv("MAYA_ONTOLOGY_DSN")

    async def _connect(self):
        import asyncpg

        return await asyncpg.connect(self._dsn)

    # -- public API ---------------------------------------------------------

    async def resolve_work(self, query: WorkQuery) -> list[WorkCandidate]:
        """Graph first; on miss/weak match consult registered schemas.

        Schema hits are written through to the graph fire-and-forget and
        returned with ``node_id=None`` (the node may not exist yet).
        """
        candidates: list[WorkCandidate] = []
        if self._dsn:
            try:
                candidates = await asyncio.wait_for(
                    self._graph_work_candidates(query), self.graph_budget_s
                )
            except Exception as exc:  # noqa: BLE001 — graph must never block resolution
                logger.warning("music graph lookup failed: %s", exc)

        if candidates and candidates[0].confidence >= self.confidence_threshold:
            return candidates

        for schema in self.schemas:
            try:
                works = await asyncio.wait_for(
                    schema.search_work(query), self.schema_budget_s
                )
            except Exception as exc:  # noqa: BLE001 — adapters are best-effort
                logger.warning("source schema %s failed: %s", schema.schema_id, exc)
                continue
            if not works:
                continue
            text = query.text or query.artist or ""
            schema_candidates = [
                WorkCandidate(
                    work=work,
                    confidence=_score(text, work.label, work.aliases) if text else 0.8,
                )
                for work in works
            ]
            schema_candidates.sort(key=lambda c: c.confidence, reverse=True)
            best = schema_candidates[0]
            recordings: tuple[Recording, ...] = ()
            fetch_recordings = getattr(schema, "fetch_recordings", None)
            if fetch_recordings is not None:
                try:
                    recs = await asyncio.wait_for(
                        fetch_recordings(best.work), self.schema_budget_s
                    )
                    if recs:
                        recordings = tuple(recs)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "source schema %s fetch_recordings failed: %s",
                        schema.schema_id,
                        exc,
                    )
            self._spawn_write_through(
                ResolutionEvent(
                    work=best.work,
                    recordings=recordings,
                    source_schema=schema.schema_id,
                    confidence=best.confidence,
                )
            )
            return schema_candidates + candidates

        return candidates

    async def resolve_recording(self, query: RecordingQuery) -> Recording | None:
        """Best recording by owning work key or exact source ref."""
        if not self._dsn:
            return None
        try:
            conn = await self._connect()
        except Exception as exc:  # noqa: BLE001
            logger.warning("music graph connect failed: %s", exc)
            return None
        try:
            if query.source_ref is not None:
                row = await conn.fetchrow(
                    """
                    SELECT id, domain_id, label, attrs
                    FROM ontology_node
                    WHERE domain = $1 AND node_type = $2 AND domain_id = $3
                    LIMIT 1
                    """,
                    DOMAIN,
                    NODE_RECORDING,
                    query.source_ref.domain_key(),
                )
            elif query.work_key:
                row = await conn.fetchrow(
                    """
                    SELECT n.id, n.domain_id, n.label, n.attrs
                    FROM ontology_node w
                    JOIN ontology_edge e ON e.source_id = w.id AND e.edge_type = $4
                    JOIN ontology_node n ON n.id = e.target_id AND n.node_type = $3
                    WHERE w.domain = $1 AND w.node_type = $2 AND w.domain_id = $5
                    ORDER BY e.confidence DESC
                    LIMIT 1
                    """,
                    DOMAIN,
                    NODE_CANONICAL_WORK,
                    NODE_RECORDING,
                    EDGE_HAS_RECORDING,
                    query.work_key,
                )
            else:
                return None
        finally:
            await conn.close()

        return _recording_from_row(row) if row is not None else None

    async def ingest(self, event: ResolutionEvent) -> str | None:
        """Awaited write-through for feed hooks (bandcamp, slskd, knowledge).

        Upserts the work, its artists, and recordings; returns the work node
        id (None when no DSN is configured). Also fires ``on_resolution``.
        """
        work_node_id = await self._write_graph(event)
        if self.on_resolution is not None:
            try:
                await self.on_resolution(event)
            except Exception as exc:  # noqa: BLE001 — hooks must not break ingest
                logger.warning("on_resolution hook failed: %s", exc)
        return work_node_id

    # -- graph reads --------------------------------------------------------

    async def _graph_work_candidates(self, query: WorkQuery) -> list[WorkCandidate]:
        where = ["domain = $1", "node_type = $2"]
        args: list[Any] = [DOMAIN, NODE_CANONICAL_WORK]
        exact = False

        if query.source_ref is not None:
            args.append(query.source_ref.domain_key())
            where.append(f"domain_id = ${len(args)}")
            exact = True
        elif query.fingerprint:
            args.append(work_key_from_fingerprint(query.fingerprint))
            where.append(f"domain_id = ${len(args)}")
            exact = True
        elif query.text:
            args.append(query.text)
            n = len(args)
            where.append(f"(label ILIKE '%' || ${n} || '%' OR attrs->'aliases' ? ${n})")
        else:
            return []

        args.append(query.limit)
        sql = (
            "SELECT id, domain_id, label, attrs FROM ontology_node "
            f"WHERE {' AND '.join(where)} "
            f"ORDER BY updated_at DESC LIMIT ${len(args)}"
        )

        conn = await self._connect()
        try:
            rows = await conn.fetch(sql, *args)
        finally:
            await conn.close()

        candidates = []
        for row in rows:
            work = _work_from_row(row)
            confidence = (
                1.0 if exact else _score(query.text or "", work.label, work.aliases)
            )
            candidates.append(
                WorkCandidate(work=work, confidence=confidence, node_id=str(row["id"]))
            )
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates

    # -- write-through ------------------------------------------------------

    def _spawn_write_through(self, event: ResolutionEvent) -> None:
        """Fire-and-forget: never blocks or fails the resolution path."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._write_through(event))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _write_through(self, event: ResolutionEvent) -> None:
        try:
            await self._write_graph(event)
        except Exception as exc:  # noqa: BLE001 — swallow-and-log by contract
            logger.warning("music graph write-through failed: %s", exc)
            return
        if self.on_resolution is not None:
            try:
                await self.on_resolution(event)
            except Exception as exc:  # noqa: BLE001
                logger.warning("on_resolution hook failed: %s", exc)

    async def _write_graph(self, event: ResolutionEvent) -> str | None:
        if not self._dsn:
            return None
        work = event.work
        conn = await self._connect()
        try:
            work_node_id = await upsert_node(
                conn,
                domain=DOMAIN,
                domain_id=work.key,
                node_type=NODE_CANONICAL_WORK,
                label=work.label,
                attrs={
                    **work.attrs,
                    "aliases": list(work.aliases),
                    "anchors": [
                        {"schema": a.schema, "external_id": a.external_id, "url": a.url}
                        for a in work.anchors
                    ],
                    "source_schema": event.source_schema,
                },
            )
            for artist in work.artists:
                artist_node_id = await upsert_artist_node(
                    conn, slug=artist.slug, label=artist.name
                )
                await link(
                    conn,
                    str(work_node_id),
                    str(artist_node_id),
                    edge_type=EDGE_PERFORMED_BY,
                    dimension=DIM_SEMANTIC,
                    confidence=event.confidence,
                )
            for recording in event.recordings:
                rec_node_id = await upsert_node(
                    conn,
                    domain=DOMAIN,
                    domain_id=recording.source.domain_key(),
                    node_type=NODE_RECORDING,
                    label=recording.title or recording.source.domain_key(),
                    attrs={
                        **recording.attrs,
                        "title": recording.title,
                        "duration_seconds": recording.duration_seconds,
                        "webpage_url": recording.webpage_url,
                        "stream_url": recording.stream_url,
                        "url": recording.source.url,
                    },
                )
                await link(
                    conn,
                    str(work_node_id),
                    str(rec_node_id),
                    edge_type=EDGE_HAS_RECORDING,
                    dimension=DIM_SEMANTIC,
                    confidence=event.confidence,
                )
            return str(work_node_id)
        finally:
            await conn.close()
