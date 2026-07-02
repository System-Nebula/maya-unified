"""voice rooms for multi-user public sessions

Revision ID: 20260703_voice_rooms
Revises: 20260702_operator_voice
Create Date: 2026-07-03 00:00:00.000000+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260703_voice_rooms"
down_revision: Union[str, None] = "20260702_operator_voice"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "voice_rooms",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("owner_operator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False, server_default="private"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("max_participants", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("personality_snapshot", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("settings_snapshot", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_operator_id"], ["operator_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_voice_rooms_slug", "voice_rooms", ["slug"])
    op.create_index("ix_voice_rooms_owner_operator_id", "voice_rooms", ["owner_operator_id"])

    op.create_table(
        "voice_room_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("guest_token_hash", sa.String(length=128), nullable=True),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="member"),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["operator_id"], ["operator_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["room_id"], ["voice_rooms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("room_id", "operator_id", name="uq_voice_room_members_room_operator"),
    )
    op.create_index("ix_voice_room_members_room_id", "voice_room_members", ["room_id"])
    op.create_index("ix_voice_room_members_guest_token_hash", "voice_room_members", ["guest_token_hash"])

    op.create_table(
        "voice_room_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["member_id"], ["voice_room_members.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["room_id"], ["voice_rooms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_room_messages_room_id", "voice_room_messages", ["room_id"])
    op.create_index("ix_voice_room_messages_ts", "voice_room_messages", ["ts"])

    op.create_table(
        "voice_room_voice_queue",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="waiting"),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["member_id"], ["voice_room_members.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["room_id"], ["voice_rooms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_voice_room_voice_queue_room_id", "voice_room_voice_queue", ["room_id"])


def downgrade() -> None:
    op.drop_index("ix_voice_room_voice_queue_room_id", table_name="voice_room_voice_queue")
    op.drop_table("voice_room_voice_queue")
    op.drop_index("ix_voice_room_messages_ts", table_name="voice_room_messages")
    op.drop_index("ix_voice_room_messages_room_id", table_name="voice_room_messages")
    op.drop_table("voice_room_messages")
    op.drop_index("ix_voice_room_members_guest_token_hash", table_name="voice_room_members")
    op.drop_index("ix_voice_room_members_room_id", table_name="voice_room_members")
    op.drop_table("voice_room_members")
    op.drop_index("ix_voice_rooms_owner_operator_id", table_name="voice_rooms")
    op.drop_index("ix_voice_rooms_slug", table_name="voice_rooms")
    op.drop_table("voice_rooms")
