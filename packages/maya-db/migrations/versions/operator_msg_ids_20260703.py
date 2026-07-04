"""Add correlation ids to operator conversation messages.

Revision ID: 20260703_msg_ids
Revises: 20260705_merge_google_operator
Create Date: 2026-07-03 00:00:00.000000+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260703_msg_ids"
down_revision: Union[str, None] = "20260705_merge_google_operator"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "operator_conversation_messages",
        sa.Column("message_id", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "operator_conversation_messages",
        sa.Column("corr_id", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "operator_conversation_messages",
        sa.Column("completion_id", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_operator_conversation_messages_message_id",
        "operator_conversation_messages",
        ["message_id"],
    )
    op.create_index(
        "ix_operator_conversation_messages_corr_id",
        "operator_conversation_messages",
        ["corr_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_operator_conversation_messages_corr_id", table_name="operator_conversation_messages")
    op.drop_index("ix_operator_conversation_messages_message_id", table_name="operator_conversation_messages")
    op.drop_column("operator_conversation_messages", "completion_id")
    op.drop_column("operator_conversation_messages", "corr_id")
    op.drop_column("operator_conversation_messages", "message_id")
