"""notifications + backfill columns

Revision ID: 20260525_notifs
Revises: 20260525_feeds
Create Date: 2026-05-25 12:00:00.000000+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260525_notifs"
down_revision: Union[str, None] = "20260525_feeds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "feed_channels",
        sa.Column("archive_indexed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "feed_videos",
        sa.Column(
            "source_phase",
            sa.String(length=16),
            nullable=False,
            server_default="live",
        ),
    )

    op.create_table(
        "feed_notifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("video_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("read", sa.Boolean(), server_default="false", nullable=False),
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
        sa.ForeignKeyConstraint(["video_id"], ["feed_videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feed_notifications_kind", "feed_notifications", ["kind"])
    op.create_index("ix_feed_notifications_read", "feed_notifications", ["read"])
    op.create_index(
        "ix_feed_notifications_read_created",
        "feed_notifications",
        ["read", "created_at"],
    )
    op.create_index(
        "ix_feed_notifications_channel_id", "feed_notifications", ["channel_id"]
    )
    op.create_index(
        "ix_feed_notifications_video_id", "feed_notifications", ["video_id"]
    )


def downgrade() -> None:
    op.drop_table("feed_notifications")
    op.drop_column("feed_videos", "source_phase")
    op.drop_column("feed_channels", "archive_indexed_at")
