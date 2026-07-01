"""Creator-intel feed database models.

Channels, videos, comment snapshots, persons, tag taxonomy, similarity edges,
and the subscription table consumed by the ingest worker.

Embedding vectors are kept as pgvector ``vector(768)`` columns. To avoid
hard-failing on installs without the pgvector python package, the column
type is loaded lazily; tests can stub it out.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from maya_db.base import Base, TimestampMixin, UUIDPrimaryKey

try:  # pgvector is an optional install; fall back to JSONB if unavailable.
    from pgvector.sqlalchemy import Vector

    _EMBED = Vector(768)
except Exception:  # pragma: no cover - exercised only without pgvector
    _EMBED = JSONB


class Channel(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "feed_channels"
    __table_args__ = (
        UniqueConstraint("platform", "platform_id", name="uq_channel_platform_id"),
    )

    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    platform_id: Mapped[str] = mapped_column(String(128), nullable=False)
    handle: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    subscriber_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    video_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    view_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    joined_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    feed_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cadence: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="weekly"
    )
    last_fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archive_indexed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    identity_confidence: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0"
    )
    profile_links: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    videos: Mapped[list["Video"]] = relationship(back_populates="channel")
    subscription: Mapped[Optional["Subscription"]] = relationship(
        back_populates="channel", uselist=False
    )


class Video(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "feed_videos"
    __table_args__ = (
        UniqueConstraint("video_id", name="uq_video_platform_id"),
    )

    channel_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feed_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    video_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    feed_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_short: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    source_phase: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="live"
    )
    thumbnail_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    view_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    like_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    comment_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    embedding = mapped_column(_EMBED, nullable=True)
    thumbnail_embedding = mapped_column(_EMBED, nullable=True)
    analysis_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    channel: Mapped[Channel] = relationship(back_populates="videos")
    snapshots: Mapped[list["CommentSnapshot"]] = relationship(back_populates="video")
    analyses: Mapped[list["FeedAnalysis"]] = relationship(back_populates="entry")
    intel_links: Mapped[list["VideoIntelLink"]] = relationship(back_populates="video")


class CommentSnapshot(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "feed_comment_snapshots"

    video_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feed_videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    fetch_window: Mapped[str] = mapped_column(String(8), nullable=False)
    total_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    video: Mapped[Video] = relationship(back_populates="snapshots")
    comments: Mapped[list["Comment"]] = relationship(back_populates="snapshot")


class Comment(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "feed_comments"

    snapshot_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feed_comment_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform_comment_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    author_handle: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    author_channel_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    like_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    reply_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    is_creator_reply: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    sentiment_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    embedding = mapped_column(_EMBED, nullable=True)

    snapshot: Mapped[CommentSnapshot] = relationship(back_populates="comments")


class Person(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "feed_persons"

    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # URL-safe operator handle (e.g. "misskatie"). Nullable for legacy rows
    # that pre-date the Following panel; new rows from /api/follow/persons
    # always set it. Uniqueness enforced at the DB level by a partial index
    # ignoring soft-deleted rows.
    slug: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="REAL"
    )
    realm: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    identity_confidence: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0"
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    links: Mapped[list["PersonChannel"]] = relationship(back_populates="person")


class PersonChannel(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "feed_person_channels"
    __table_args__ = (
        UniqueConstraint("person_id", "channel_id", name="uq_person_channel"),
    )

    person_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feed_persons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feed_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    signals: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )

    person: Mapped[Person] = relationship(back_populates="links")


class TagNode(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "feed_tag_nodes"

    canonical_path: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    embedding = mapped_column(_EMBED, nullable=True)


class VideoTag(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "feed_video_tags"
    __table_args__ = (
        UniqueConstraint("video_id", "tag_id", name="uq_video_tag"),
    )

    video_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feed_videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feed_tag_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="1"
    )


class ChannelTag(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "feed_channel_tags"
    __table_args__ = (
        UniqueConstraint("channel_id", "tag_id", name="uq_channel_tag"),
    )

    channel_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feed_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feed_tag_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="1"
    )


class VideoSimilarity(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "feed_video_similarity"
    __table_args__ = (
        UniqueConstraint("video_a_id", "video_b_id", name="uq_video_pair"),
    )

    video_a_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feed_videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    video_b_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feed_videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)


class Subscription(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "feed_subscriptions"

    channel_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feed_channels.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    cadence: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="weekly"
    )
    fetch_comments: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    comment_windows: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default='["t24h","t72h","t1w"]'
    )
    analysis_config: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )

    channel: Mapped[Channel] = relationship(back_populates="subscription")


class Notification(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "feed_notifications"

    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    channel_id: Mapped[Optional[UUID]] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feed_channels.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    video_id: Mapped[Optional[UUID]] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feed_videos.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", index=True
    )
    operator_id: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="local", index=True
    )


class OperatorPreferences(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "operator_preferences"

    operator_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    genre_weights: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    source_enabled: Mapped[dict[str, bool]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    source_trust: Mapped[dict[str, float]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    metro: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    window_default: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default="7d"
    )


class OperatorSourceToken(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "operator_source_tokens"
    __table_args__ = (
        UniqueConstraint("operator_id", "source", name="uq_operator_source_tokens_operator_source"),
    )

    operator_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    token_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class CollectionSummary(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "collection_summary"

    operator_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    vinyl_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    digital_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    wantlist_matches: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class KnowledgeItem(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "knowledge_items"

    operator_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    source_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="email_newsletter"
    )
    artist_slug: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    artist_display: Mapped[str] = mapped_column(String(255), nullable=False)
    item_type: Mapped[str] = mapped_column(String(32), nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    track: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    album: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    release_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    promo: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    handwritten_note: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    html_artifact_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="text/html"
    )
    text_fallback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ontology_artist_id: Mapped[Optional[UUID]] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    brand_color: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    extras: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class Follow(Base, UUIDPrimaryKey, TimestampMixin):
    """Operator-facing follow row with polymorphic subject (Person or Channel).

    Distinct from :class:`Subscription` (which represents the ingest-side
    "this channel is being polled" flag): Follow rows carry per-operator
    notification prefs and can target either a Person (inherits to all
    attached channels) or a Channel (overrides Person-level prefs).
    """

    __tablename__ = "feed_follows"

    operator_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), nullable=False, index=True
    )
    cadence: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="weekly"
    )
    notify_homepage: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    notify_discord: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    mpv_autolaunch: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    muted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    notification_feed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    last_notified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class FeedAnalysis(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "feed_analyses"

    channel_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feed_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entry_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feed_videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    from_tag: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    to_tag: Mapped[str] = mapped_column(String(128), nullable=False)
    release_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="done"
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    channel: Mapped[Channel] = relationship()
    entry: Mapped[Video] = relationship(back_populates="analyses")


class IntelItem(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "feed_intel_items"

    canonical_url: Mapped[str] = mapped_column(
        Text, nullable=False, unique=True, index=True
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="unknown"
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default="{}"
    )

    video_links: Mapped[list["VideoIntelLink"]] = relationship(
        back_populates="intel_item"
    )


class VideoIntelLink(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "feed_video_intel_links"
    __table_args__ = (
        UniqueConstraint("video_id", "intel_item_id", name="uq_video_intel_item"),
    )

    video_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feed_videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    intel_item_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feed_intel_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    timestamp_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    video: Mapped[Video] = relationship(back_populates="intel_links")
    intel_item: Mapped[IntelItem] = relationship(back_populates="video_links")
