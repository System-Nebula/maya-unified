"""feed intel tables: release analyses, intel items, video links

Revision ID: 20260607_intel
Revises: 20260525_follow
Create Date: 2026-06-07 00:00:00.000000+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260607_intel"
down_revision: Union[str, None] = "20260525_follow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "feed_videos",
        sa.Column("analysis_status", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "feed_subscriptions",
        sa.Column("analysis_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.create_table(
        "feed_analyses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("from_tag", sa.String(length=128), nullable=True),
        sa.Column("to_tag", sa.String(length=128), nullable=False),
        sa.Column("release_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="done", nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["channel_id"], ["feed_channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entry_id"], ["feed_videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feed_analyses_channel_id", "feed_analyses", ["channel_id"])
    op.create_index("ix_feed_analyses_entry_id", "feed_analyses", ["entry_id"])

    op.create_table(
        "feed_intel_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_url"),
    )
    op.create_index("ix_feed_intel_items_canonical_url", "feed_intel_items", ["canonical_url"])

    op.create_table(
        "feed_video_intel_links",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("video_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("intel_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("timestamp_seconds", sa.Integer(), nullable=True),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["intel_item_id"], ["feed_intel_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_id"], ["feed_videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("video_id", "intel_item_id", name="uq_video_intel_item"),
    )
    op.create_index(
        "ix_feed_video_intel_links_video_id", "feed_video_intel_links", ["video_id"]
    )
    op.create_index(
        "ix_feed_video_intel_links_intel_item_id",
        "feed_video_intel_links",
        ["intel_item_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_feed_video_intel_links_intel_item_id", table_name="feed_video_intel_links")
    op.drop_index("ix_feed_video_intel_links_video_id", table_name="feed_video_intel_links")
    op.drop_table("feed_video_intel_links")
    op.drop_index("ix_feed_intel_items_canonical_url", table_name="feed_intel_items")
    op.drop_table("feed_intel_items")
    op.drop_index("ix_feed_analyses_entry_id", table_name="feed_analyses")
    op.drop_index("ix_feed_analyses_channel_id", table_name="feed_analyses")
    op.drop_table("feed_analyses")
    op.drop_column("feed_subscriptions", "analysis_config")
    op.drop_column("feed_videos", "analysis_status")
