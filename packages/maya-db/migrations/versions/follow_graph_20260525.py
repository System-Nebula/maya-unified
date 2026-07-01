"""operator follow graph: persons.slug/kind/realm + feed_follows

Revision ID: 20260525_follow
Revises: 20260525_notifs
Create Date: 2026-05-25 16:30:00.000000+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260525_follow"
down_revision: Union[str, None] = "20260525_notifs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- extend feed_persons with operator-management fields ---
    op.add_column("feed_persons", sa.Column("slug", sa.String(length=64), nullable=True))
    op.add_column(
        "feed_persons",
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="REAL"),
    )
    op.add_column("feed_persons", sa.Column("realm", sa.String(length=64), nullable=True))
    op.add_column(
        "feed_persons",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Unique slug for live (non-deleted) rows — operators reuse the same handle
    # for resurrected entities.
    op.create_index(
        "ix_feed_persons_slug_live",
        "feed_persons",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND slug IS NOT NULL"),
    )

    # --- soft-delete column on feed_channels ---
    op.add_column(
        "feed_channels",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- new feed_follows table (operator-facing polymorphic subscriptions) ---
    op.create_table(
        "feed_follows",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("operator_id", sa.String(length=64), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "cadence", sa.String(length=16), nullable=False, server_default="weekly"
        ),
        sa.Column(
            "notify_homepage", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "notify_discord", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "mpv_autolaunch", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("muted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index("ix_feed_follows_operator_id", "feed_follows", ["operator_id"])
    op.create_index("ix_feed_follows_subject_id", "feed_follows", ["subject_id"])
    # One live row per (operator, subject) — partial so re-following after a
    # soft delete creates a new row instead of resurrecting the old one.
    op.create_index(
        "ix_feed_follows_unique_live",
        "feed_follows",
        ["operator_id", "subject_type", "subject_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_feed_follows_unique_live", table_name="feed_follows")
    op.drop_index("ix_feed_follows_subject_id", table_name="feed_follows")
    op.drop_index("ix_feed_follows_operator_id", table_name="feed_follows")
    op.drop_table("feed_follows")

    op.drop_column("feed_channels", "deleted_at")

    op.drop_index("ix_feed_persons_slug_live", table_name="feed_persons")
    op.drop_column("feed_persons", "deleted_at")
    op.drop_column("feed_persons", "realm")
    op.drop_column("feed_persons", "kind")
    op.drop_column("feed_persons", "slug")
