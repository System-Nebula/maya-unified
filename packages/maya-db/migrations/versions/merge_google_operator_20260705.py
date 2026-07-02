"""Merge Google OAuth and operator voice migration branches."""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260705_merge_google_operator"
down_revision: Union[str, tuple[str, ...], None] = (
    "20260702_oauth_pkce_redirect_uri",
    "20260704_operator_admin",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
