"""Persistence layer for AtomicNotes and edges (sync SQLAlchemy)."""

from __future__ import annotations

import os
from typing import Any, Iterable, Sequence

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from maya_db.models import AtomicNote, NoteEdge
from mia_docs.predicates import Predicate

_DEFAULT_URL = "postgresql+asyncpg://maya:maya@localhost:5433/maya"


def sync_database_url() -> str:
    url = os.getenv("DATABASE_URL", _DEFAULT_URL)
    return url.replace("+asyncpg", "+psycopg2")


_session_factory: sessionmaker | None = None


def get_session() -> Session:
    global _session_factory
    if _session_factory is None:
        engine = create_engine(sync_database_url(), pool_pre_ping=True)
        _session_factory = sessionmaker(engine, expire_on_commit=False)
    return _session_factory()


def upsert_note(
    session: Session,
    *,
    id: str,
    title: str,
    content: str,
    note_type: str,
    labels: list[str] | None = None,
    meta: dict[str, Any] | None = None,
    embedding: list[float] | None = None,
    source_doc_hash: str | None = None,
    page_start: int | None = None,
    page_end: int | None = None,
    valid_start=None,
) -> AtomicNote:
    """Insert, or version-bump on existing id (same content hash = same id)."""
    note = session.get(AtomicNote, id)
    if note is None:
        note = AtomicNote(
            id=id,
            title=title,
            content=content,
            note_type=note_type,
            labels=labels or [],
            meta=meta or {},
            embedding=embedding,
            source_doc_hash=source_doc_hash,
            page_start=page_start,
            page_end=page_end,
            valid_start=valid_start,
        )
        session.add(note)
    else:
        note.version = (note.version or 1) + 1
        note.title = title
        note.content = content
        note.labels = labels or note.labels
        note.meta = {**(note.meta or {}), **(meta or {})}
        if embedding is not None:
            note.embedding = embedding
    return note


def upsert_edge(
    session: Session,
    src_id: str,
    dst_id: str,
    predicate: Predicate,
    meta: dict[str, Any] | None = None,
    weight: float | None = None,
) -> None:
    edge = session.get(NoteEdge, (src_id, dst_id, predicate.value))
    if edge is None:
        session.add(
            NoteEdge(
                src_id=src_id,
                dst_id=dst_id,
                predicate=predicate.value,
                meta=meta or {},
                weight=weight,
            )
        )
    else:
        edge.meta = meta or edge.meta
        edge.weight = weight if weight is not None else edge.weight


def neighbors(
    session: Session,
    note_ids: Sequence[str],
    predicates: Iterable[Predicate] | None = None,
    cap_per_note: int = 5,
) -> dict[str, list[tuple[NoteEdge, AtomicNote]]]:
    """Outgoing 1-hop edges for each note, capped server-side."""
    if not note_ids:
        return {}
    stmt = select(NoteEdge, AtomicNote).join(
        AtomicNote, NoteEdge.dst_id == AtomicNote.id
    ).where(NoteEdge.src_id.in_(list(note_ids)))
    if predicates is not None:
        stmt = stmt.where(NoteEdge.predicate.in_([p.value for p in predicates]))
    # deterministic order so downstream renders are idempotent
    stmt = stmt.order_by(NoteEdge.predicate, NoteEdge.dst_id)
    out: dict[str, list[tuple[NoteEdge, AtomicNote]]] = {}
    for edge, note in session.execute(stmt):
        bucket = out.setdefault(edge.src_id, [])
        if len(bucket) < cap_per_note:
            bucket.append((edge, note))
    return out


def vector_candidates(
    session: Session,
    query_embedding: list[float],
    note_type: str | None = None,
    labels: list[str] | None = None,
    meta_filters: dict[str, tuple[str, Any]] | None = None,
    limit: int = 40,
) -> list[tuple[AtomicNote, float]]:
    """SQL prune first (type/labels/metadata), then pgvector cosine recall."""
    where = ["embedding IS NOT NULL"]
    params: dict[str, Any] = {
        "qv": "[" + ",".join(f"{x:.8f}" for x in query_embedding) + "]",
        "lim": limit,
    }
    if note_type:
        where.append("note_type = :nt")
        params["nt"] = note_type
    if labels:
        for i, lb in enumerate(labels):
            where.append(f"labels @> :lb{i}")
            params[f"lb{i}"] = f'["{lb}"]'
    if meta_filters:
        for i, (key, (op, val)) in enumerate(meta_filters.items()):
            cast = "::numeric" if isinstance(val, (int, float)) else ""
            where.append(f"(metadata->>'{key}'){cast} {op} :mv{i}")
            params[f"mv{i}"] = val
    sql = text(
        f"""
        SELECT id, 1 - (embedding <=> CAST(:qv AS vector)) AS score
        FROM kb_atomic_notes
        WHERE {' AND '.join(where)}
        ORDER BY embedding <=> CAST(:qv AS vector)
        LIMIT :lim
        """
    )
    rows = session.execute(sql, params).all()
    if not rows:
        return []
    ids = [r.id for r in rows]
    scores = {r.id: float(r.score) for r in rows}
    notes = session.execute(
        select(AtomicNote).where(AtomicNote.id.in_(ids))
    ).scalars().all()
    by_id = {n.id: n for n in notes}
    return [(by_id[i], scores[i]) for i in ids if i in by_id]
