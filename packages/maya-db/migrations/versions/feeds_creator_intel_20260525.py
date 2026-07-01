"""creator-intel feed tables

Revision ID: 20260525_feeds
Revises: 20260512_195810
Create Date: 2026-05-25 00:00:00.000000+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260525_feeds"
down_revision: Union[str, None] = "20260512_195810"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _embedding_column() -> sa.Column:
    try:
        from pgvector.sqlalchemy import Vector

        return sa.Column("embedding", Vector(768), nullable=True)
    except Exception:  # pragma: no cover
        return sa.Column("embedding", postgresql.JSONB(astext_type=sa.Text()), nullable=True)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "feed_channels",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("platform_id", sa.String(length=128), nullable=False),
        sa.Column("handle", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("subscriber_count", sa.Integer(), nullable=True),
        sa.Column("video_count", sa.Integer(), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feed_url", sa.Text(), nullable=True),
        sa.Column("cadence", sa.String(length=16), server_default="weekly", nullable=False),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("identity_confidence", sa.Float(), server_default="0", nullable=False),
        sa.Column("profile_links", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform", "platform_id", name="uq_channel_platform_id"),
    )
    op.create_index("ix_feed_channels_platform", "feed_channels", ["platform"])
    op.create_index("ix_feed_channels_handle", "feed_channels", ["handle"])

    try:
        from pgvector.sqlalchemy import Vector
        embed_type = Vector(768)
    except Exception:  # pragma: no cover
        embed_type = postgresql.JSONB(astext_type=sa.Text())

    op.create_table(
        "feed_videos",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("video_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("feed_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("is_short", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=True),
        sa.Column("like_count", sa.Integer(), nullable=True),
        sa.Column("comment_count", sa.Integer(), nullable=True),
        sa.Column("embedding", embed_type, nullable=True),
        sa.Column("thumbnail_embedding", embed_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["feed_channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("video_id", name="uq_video_platform_id"),
    )
    op.create_index("ix_feed_videos_channel_id", "feed_videos", ["channel_id"])
    op.create_index("ix_feed_videos_published_at", "feed_videos", ["published_at"])

    op.create_table(
        "feed_comment_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("video_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetch_window", sa.String(length=8), nullable=False),
        sa.Column("total_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["video_id"], ["feed_videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feed_comment_snapshots_video_id", "feed_comment_snapshots", ["video_id"])

    op.create_table(
        "feed_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform_comment_id", sa.String(length=128), nullable=False),
        sa.Column("author_handle", sa.String(length=255), nullable=True),
        sa.Column("author_channel_id", sa.String(length=128), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("like_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reply_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_creator_reply", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        sa.Column("embedding", embed_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["feed_comment_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feed_comments_snapshot_id", "feed_comments", ["snapshot_id"])
    op.create_index("ix_feed_comments_platform_comment_id", "feed_comments", ["platform_comment_id"])
    op.create_index("ix_feed_comments_author_channel_id", "feed_comments", ["author_channel_id"])

    op.create_table(
        "feed_persons",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("identity_confidence", sa.Float(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "feed_person_channels",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("signals", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["feed_persons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["feed_channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("person_id", "channel_id", name="uq_person_channel"),
    )
    op.create_index("ix_feed_person_channels_person_id", "feed_person_channels", ["person_id"])
    op.create_index("ix_feed_person_channels_channel_id", "feed_person_channels", ["channel_id"])

    op.create_table(
        "feed_tag_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("canonical_path", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("embedding", embed_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_path"),
    )
    op.create_index("ix_feed_tag_nodes_canonical_path", "feed_tag_nodes", ["canonical_path"])

    for tbl, parent in (("feed_video_tags", "feed_videos"), ("feed_channel_tags", "feed_channels")):
        parent_col = "video_id" if parent == "feed_videos" else "channel_id"
        op.create_table(
            tbl,
            sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
            sa.Column(parent_col, postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("confidence", sa.Float(), server_default="1", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint([parent_col], [f"{parent}.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["tag_id"], ["feed_tag_nodes.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(parent_col, "tag_id", name=f"uq_{tbl}"),
        )

    op.create_table(
        "feed_video_similarity",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("video_a_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("video_b_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["video_a_id"], ["feed_videos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_b_id"], ["feed_videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("video_a_id", "video_b_id", name="uq_video_pair"),
    )
    op.create_index("ix_feed_video_similarity_video_a_id", "feed_video_similarity", ["video_a_id"])

    op.create_table(
        "feed_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cadence", sa.String(length=16), server_default="weekly", nullable=False),
        sa.Column("fetch_comments", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("comment_windows", postgresql.JSONB(astext_type=sa.Text()), server_default='["t24h","t72h","t1w"]', nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["feed_channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel_id"),
    )

    # ivfflat indexes for similarity search; only effective when pgvector is installed.
    try:
        from pgvector.sqlalchemy import Vector  # noqa: F401

        op.execute(
            "CREATE INDEX ix_feed_videos_embedding "
            "ON feed_videos USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )
        op.execute(
            "CREATE INDEX ix_feed_comments_embedding "
            "ON feed_comments USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
        )
        op.execute(
            "CREATE INDEX ix_feed_tag_nodes_embedding "
            "ON feed_tag_nodes USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50)"
        )
    except Exception:  # pragma: no cover
        pass


def downgrade() -> None:
    for tbl in (
        "feed_subscriptions",
        "feed_video_similarity",
        "feed_channel_tags",
        "feed_video_tags",
        "feed_tag_nodes",
        "feed_person_channels",
        "feed_persons",
        "feed_comments",
        "feed_comment_snapshots",
        "feed_videos",
        "feed_channels",
    ):
        op.drop_table(tbl)
