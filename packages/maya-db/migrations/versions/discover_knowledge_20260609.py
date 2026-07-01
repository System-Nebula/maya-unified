"""discover knowledge items — email newsletter capture

Revision ID: 20260609_knowledge
Revises: 20260608_discover
Create Date: 2026-06-09 00:00:00.000000+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260609_knowledge"
down_revision: Union[str, None] = "20260608_discover"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("operator_id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column(
            "source_kind",
            sa.String(length=32),
            nullable=False,
            server_default="email_newsletter",
        ),
        sa.Column("artist_slug", sa.String(length=128), nullable=False),
        sa.Column("artist_display", sa.String(length=255), nullable=False),
        sa.Column("item_type", sa.String(length=32), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("track", sa.Text(), nullable=True),
        sa.Column("album", sa.Text(), nullable=True),
        sa.Column("release_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("promo", sa.Text(), nullable=True),
        sa.Column(
            "handwritten_note",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("html_artifact_key", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("text_fallback", sa.Text(), nullable=True),
        sa.Column("ontology_artist_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("brand_color", sa.String(length=16), nullable=True),
        sa.Column("extras", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
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
    op.create_index(
        "ix_knowledge_items_operator_artist_received",
        "knowledge_items",
        ["operator_id", "artist_slug", "received_at"],
    )
    op.create_index(
        "ix_knowledge_items_received_at",
        "knowledge_items",
        ["received_at"],
    )

    op.add_column(
        "feed_follows",
        sa.Column(
            "notification_feed",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )


def downgrade() -> None:
    op.drop_column("feed_follows", "notification_feed")
    op.drop_index("ix_knowledge_items_received_at", table_name="knowledge_items")
    op.drop_index(
        "ix_knowledge_items_operator_artist_received",
        table_name="knowledge_items",
    )
    op.drop_table("knowledge_items")
