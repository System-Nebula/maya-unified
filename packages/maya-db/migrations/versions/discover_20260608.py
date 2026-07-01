"""discover: operator preferences, collection summary, per-operator notifications

Revision ID: 20260608_discover
Revises: 20260607_intel
Create Date: 2026-06-08 00:00:00.000000+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260608_discover"
down_revision: Union[str, None] = "20260607_intel"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "feed_notifications",
        sa.Column(
            "operator_id",
            sa.String(length=64),
            nullable=False,
            server_default="local",
        ),
    )
    op.create_index(
        "ix_feed_notifications_operator_read_created",
        "feed_notifications",
        ["operator_id", "read", "created_at"],
    )

    op.create_table(
        "operator_preferences",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("operator_id", sa.String(length=64), nullable=False),
        sa.Column(
            "genre_weights",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "source_enabled",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "source_trust",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("metro", sa.String(length=64), nullable=True),
        sa.Column(
            "window_default",
            sa.String(length=8),
            nullable=False,
            server_default="7d",
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
        sa.UniqueConstraint("operator_id", name="uq_operator_preferences_operator"),
    )
    op.create_index(
        "ix_operator_preferences_operator_id",
        "operator_preferences",
        ["operator_id"],
    )

    op.create_table(
        "operator_source_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("operator_id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("token_data", postgresql.JSONB(), nullable=False),
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
        sa.UniqueConstraint(
            "operator_id",
            "source",
            name="uq_operator_source_tokens_operator_source",
        ),
    )

    op.create_table(
        "collection_summary",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("operator_id", sa.String(length=64), nullable=False),
        sa.Column(
            "vinyl_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "digital_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "wantlist_matches",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("operator_id", name="uq_collection_summary_operator"),
    )


def downgrade() -> None:
    op.drop_table("collection_summary")
    op.drop_table("operator_source_tokens")
    op.drop_table("operator_preferences")
    op.drop_index(
        "ix_feed_notifications_operator_read_created",
        table_name="feed_notifications",
    )
    op.drop_column("feed_notifications", "operator_id")
