"""AtomicNote knowledge-base models (mia-docs / sk CLI)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from maya_db.base import Base, TimestampMixin

try:
    from pgvector.sqlalchemy import Vector

    _EMBED = Vector(384)
    _IMAGE_EMBED = Vector(512)  # CLIP ViT-B/32
except Exception:  # pragma: no cover
    _EMBED = JSONB
    _IMAGE_EMBED = JSONB


class AtomicNote(Base, TimestampMixin):
    """Atomic knowledge note with a deterministic content-derived id.

    id = sha256(block text + source doc hash + page range) so re-ingesting
    the same content upserts (version bump) instead of duplicating.
    """

    __tablename__ = "kb_atomic_notes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    note_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    labels: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}"
    )
    valid_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valid_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_doc_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    page_start: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    page_end: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    embedding = mapped_column(_EMBED, nullable=True)


class NoteImage(Base, TimestampMixin):
    """Image extracted from a source document, linked to an AtomicNote.

    id = sha256 of the image bytes, so re-ingest dedups naturally.
    """

    __tablename__ = "kb_note_images"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    note_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("kb_atomic_notes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_doc_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}"
    )
    embedding = mapped_column(_IMAGE_EMBED, nullable=True)


class NoteEdge(Base, TimestampMixin):
    """Typed edge between two AtomicNotes (predicate is a Predicate value)."""

    __tablename__ = "kb_note_edges"

    src_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("kb_atomic_notes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    dst_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("kb_atomic_notes.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    predicate: Mapped[str] = mapped_column(String(32), primary_key=True)
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}"
    )
    weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
