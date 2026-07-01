"""Research agent persistence models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from maya_db.base import Base, TimestampMixin, UUIDPrimaryKey

try:
    from pgvector.sqlalchemy import Vector

    _EMBED = Vector(768)
except Exception:  # pragma: no cover
    _EMBED = JSONB


class ResearchRun(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "research_runs"

    operator_id: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="local", index=True
    )
    brief: Mapped[str] = mapped_column(Text, nullable=False)
    depth: Mapped[str] = mapped_column(String(16), nullable=False, server_default="shallow")
    source_mask: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default='["web","reddit","local","graph"]'
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending", index=True
    )
    plan: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    plan_approved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    prior_research_ids: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    prior_research: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    report: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    artifact_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    artifact_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    progress: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    errors: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    discord_thread_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    seed_urls: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    brief_embedding = mapped_column(_EMBED, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delta_mode: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    delta_since: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    sources: Mapped[list["ResearchSource"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    sentiments: Mapped[list["ResearchSentiment"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ResearchSource(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "research_sources"

    run_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("research_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    domain: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    credibility_score: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0.5"
    )
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    artifact_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    operator_visited: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}"
    )

    run: Mapped[ResearchRun] = relationship(back_populates="sources")


class ResearchSentiment(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "research_sentiments"

    run_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("research_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subreddit: Mapped[str] = mapped_column(String(128), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    run: Mapped[ResearchRun] = relationship(back_populates="sentiments")


class ResearchTopicEmbedding(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "research_topic_embeddings"

    run_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("research_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(_EMBED, nullable=False)


class BrowserHistoryEmbedding(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "browser_history_embeddings"

    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    embedding = mapped_column(_EMBED, nullable=False)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
