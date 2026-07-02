"""operator ban + personality flags

Revision ID: 20260704_operator_admin
Revises: 20260703_voice_rooms
Create Date: 2026-07-04 00:00:00.000000+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260704_operator_admin"
down_revision: Union[str, None] = "20260703_voice_rooms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "operator_users",
        sa.Column("is_banned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("operator_users", "is_banned")
