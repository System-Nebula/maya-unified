"""operator voice workspace tables

Revision ID: 20260702_operator_voice
Revises: 20260701_operator_users
Create Date: 2026-07-02 00:00:00.000000+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260702_operator_voice"
down_revision: Union[str, None] = "20260701_operator_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "operator_voice_settings",
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("settings", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["operator_id"], ["operator_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("operator_id"),
    )
    op.create_table(
        "operator_personalities",
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("active_slug", sa.String(length=128), nullable=False, server_default="default"),
        sa.Column("personalities", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["operator_id"], ["operator_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("operator_id"),
    )
    op.create_table(
        "operator_conversation_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["operator_id"], ["operator_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_operator_conversation_sessions_operator_id",
        "operator_conversation_sessions",
        ["operator_id"],
    )
    op.create_table(
        "operator_conversation_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["operator_id"], ["operator_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["operator_conversation_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_operator_conversation_messages_session_id", "operator_conversation_messages", ["session_id"])
    op.create_index("ix_operator_conversation_messages_operator_id", "operator_conversation_messages", ["operator_id"])
    op.create_index("ix_operator_conversation_messages_ts", "operator_conversation_messages", ["ts"])


def downgrade() -> None:
    op.drop_index("ix_operator_conversation_messages_ts", table_name="operator_conversation_messages")
    op.drop_index("ix_operator_conversation_messages_operator_id", table_name="operator_conversation_messages")
    op.drop_index("ix_operator_conversation_messages_session_id", table_name="operator_conversation_messages")
    op.drop_table("operator_conversation_messages")
    op.drop_index("ix_operator_conversation_sessions_operator_id", table_name="operator_conversation_sessions")
    op.drop_table("operator_conversation_sessions")
    op.drop_table("operator_personalities")
    op.drop_table("operator_voice_settings")
