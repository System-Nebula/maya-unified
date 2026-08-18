"""Merge KB and msg/capture heads so Alembic has a single tip.

Revision ID: 20260712_merge_kb
Revises: 20260712_kb, 20260712_merge_msg_cap
"""

from __future__ import annotations

from typing import Sequence, Union

revision: str = "20260712_merge_kb"
down_revision: Union[str, tuple[str, ...], None] = (
    "20260712_kb",
    "20260712_merge_msg_cap",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
