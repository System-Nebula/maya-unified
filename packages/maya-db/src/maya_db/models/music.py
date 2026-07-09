"""Music ontology relational tier — hard identity + cross-platform linking.

Distilled from the private 17-table music schema: only identity-bearing
tables live here (genre hierarchy, artists, canonical tracks, platform
links, releases). Soft/semantic relations (similar_to, derived_from,
same_as, in_genre) live exclusively in the ontology property graph
(maya_graph.music) — see the bridge keys below.

Bridge to the graph tier (no cross-tier FKs; the graph may be a different DSN):
- ``MusicTrack.canonical_work_key`` ↔ ontology_node(domain='music',
  node_type='canonical_work', domain_id=key). Keys are schema-prefixed
  (``wd:Q…``, ``fp:<fingerprint>``) — no external source is privileged.
- ``MusicPlatformLink (platform, external_id)`` is 1:1 with recording nodes
  whose domain_id = "{platform}:{external_id}" by construction.
- ``graph_node_id`` columns are nullable caches of ontology_node.id; on
  miss/stale, re-resolve via the keys above and rewrite.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from maya_db.base import Base, TimestampMixin, UUIDPrimaryKey


class MusicGenre(Base, UUIDPrimaryKey, TimestampMixin):
    """Genre hierarchy (Beatport-seeded but source-neutral)."""

    __tablename__ = "music_genre"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_music_genre_slug"),
        UniqueConstraint("beatport_id", name="uq_music_genre_beatport_id"),
        Index("ix_music_genre_parent", "parent_id"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("music_genre.id", ondelete="SET NULL")
    )
    beatport_id: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'beatport'")
    )
    attrs: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    parent: Mapped["MusicGenre | None"] = relationship(
        remote_side="MusicGenre.id", back_populates="children"
    )
    children: Mapped[list["MusicGenre"]] = relationship(back_populates="parent")


class MusicArtist(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "music_artist"
    __table_args__ = (
        Index("ix_music_artist_name_lower", func.lower(text("name"))),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    sort_name: Mapped[str | None] = mapped_column(Text)
    artist_type: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'artist'")
    )
    country_code: Mapped[str | None] = mapped_column(String(8))
    is_group: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    aliases: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    attrs: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Cached ontology_node.id (artist node, domain_id = slugified name). No FK.
    graph_node_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))

    tracks: Mapped[list["MusicTrack"]] = relationship(back_populates="primary_artist")


class MusicTrack(Base, UUIDPrimaryKey, TimestampMixin):
    """Canonical track identity: fingerprint-deduplicated across sources."""

    __tablename__ = "music_track"
    __table_args__ = (
        UniqueConstraint("canonical_fingerprint", name="uq_music_track_fingerprint"),
        Index("ix_music_track_cluster", "cluster_key"),
        Index("ix_music_track_isrc", "isrc"),
        Index("ix_music_track_work_key", "canonical_work_key"),
        Index("ix_music_track_primary_artist", "primary_artist_id"),
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    base_title: Mapped[str | None] = mapped_column(Text)
    remix_name: Mapped[str | None] = mapped_column(Text)
    remix_artist: Mapped[str | None] = mapped_column(Text)
    version_type: Mapped[str | None] = mapped_column(String(32))  # original|remix|edit|live|acoustic|vip
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    isrc: Mapped[str | None] = mapped_column(String(32))
    canonical_fingerprint: Mapped[str] = mapped_column(String(255), nullable=False)
    cluster_key: Mapped[str | None] = mapped_column(String(64))
    bpm: Mapped[float | None] = mapped_column(Float)
    key_camelot: Mapped[str | None] = mapped_column(String(8))
    primary_artist_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("music_artist.id", ondelete="SET NULL")
    )
    genre_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("music_genre.id", ondelete="SET NULL")
    )
    sub_genre_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("music_genre.id", ondelete="SET NULL")
    )
    # Bridge key: ontology canonical_work domain_id ("wd:Q…" | "fp:…"). No FK.
    canonical_work_key: Mapped[str | None] = mapped_column(String(64))
    graph_node_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True))
    attrs: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    primary_artist: Mapped["MusicArtist | None"] = relationship(
        back_populates="tracks", foreign_keys=[primary_artist_id]
    )
    genre: Mapped["MusicGenre | None"] = relationship(foreign_keys=[genre_id])
    sub_genre: Mapped["MusicGenre | None"] = relationship(foreign_keys=[sub_genre_id])
    artist_links: Mapped[list["MusicTrackArtist"]] = relationship(
        back_populates="track", cascade="all, delete-orphan"
    )


class MusicTrackArtist(Base, UUIDPrimaryKey):
    """Track ↔ artist with role + billing order."""

    __tablename__ = "music_track_artist"
    __table_args__ = (
        UniqueConstraint(
            "track_id", "artist_id", "role", "billing_order",
            name="uq_music_track_artist",
        ),
        Index("ix_music_track_artist_artist", "artist_id"),
    )

    track_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("music_track.id", ondelete="CASCADE"),
        nullable=False,
    )
    artist_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("music_artist.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'primary'")
    )  # primary|featured|remixer|producer
    billing_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )

    track: Mapped["MusicTrack"] = relationship(back_populates="artist_links")
    artist: Mapped["MusicArtist"] = relationship()


class MusicRelease(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "music_release"

    title: Mapped[str] = mapped_column(Text, nullable=False)
    release_type: Mapped[str | None] = mapped_column(String(32))  # album|ep|single|compilation
    label: Mapped[str | None] = mapped_column(Text)
    catalog_number: Mapped[str | None] = mapped_column(String(64))
    release_date: Mapped[date | None] = mapped_column(Date)
    primary_artist_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("music_artist.id", ondelete="SET NULL")
    )
    attrs: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    tracks: Mapped[list["MusicReleaseTrack"]] = relationship(
        back_populates="release", cascade="all, delete-orphan"
    )


class MusicReleaseTrack(Base, UUIDPrimaryKey):
    __tablename__ = "music_release_track"
    __table_args__ = (
        UniqueConstraint("release_id", "track_id", name="uq_music_release_track"),
    )

    release_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("music_release.id", ondelete="CASCADE"),
        nullable=False,
    )
    track_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("music_track.id", ondelete="CASCADE"),
        nullable=False,
    )
    disc_number: Mapped[int | None] = mapped_column(Integer)
    track_number: Mapped[int | None] = mapped_column(Integer)

    release: Mapped["MusicRelease"] = relationship(back_populates="tracks")
    track: Mapped["MusicTrack"] = relationship()


class MusicPlatformLink(Base, UUIDPrimaryKey, TimestampMixin):
    """Cross-source identity spine: one external id on one platform.

    Rows are 1:1 with graph recording nodes by construction:
    recording domain_id == f"{platform}:{external_id}".
    """

    __tablename__ = "music_platform_link"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_music_platform_ext"),
        UniqueConstraint(
            "entity_type", "entity_id", "platform", "external_id",
            name="uq_music_platform_entity",
        ),
        Index("ix_music_platform_link_entity", "entity_type", "entity_id"),
    )

    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)  # artist|track|release|genre
    entity_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)  # discogs|soundcloud|spotify|beatport|bandcamp|yt|slskd|1001tl|apple_music
    external_id: Mapped[str | None] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=text("1.0")
    )
    source: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'manual'")
    )  # manual|resolver|schema:<id>|enrich
    attrs: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class MusicReaction(Base, UUIDPrimaryKey, TimestampMixin):
    """Operator reactions on canonical works, set entries, or DJ sets."""

    __tablename__ = "music_reaction"
    __table_args__ = (
        UniqueConstraint(
            "operator_id", "entity_type", "entity_key", "reaction",
            name="uq_music_reaction_operator_entity",
        ),
        Index("ix_music_reaction_entity", "entity_type", "entity_key"),
    )

    operator_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)  # work|set_entry|set|recording
    entity_key: Mapped[str] = mapped_column(String(255), nullable=False)
    reaction: Mapped[str] = mapped_column(String(16), nullable=False)  # like|star|heart
    source_url: Mapped[str | None] = mapped_column(Text)
    attrs: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
