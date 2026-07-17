"""Merge operator msg_ids and browser_capture heads (DB-001).

Revision ID: 20260712_merge_msg_ids_browser_capture
Revises: 20260703_msg_ids, 20260708_browser_capture
"""

from __future__ import annotations

from typing import Sequence, Union

revision: str = "20260712_merge_msg_ids_browser_capture"
down_revision: Union[str, tuple[str, ...], None] = (
    "20260703_msg_ids",
    "20260708_browser_capture",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
