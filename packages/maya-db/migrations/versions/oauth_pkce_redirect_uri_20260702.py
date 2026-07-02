"""oauth pkce states: store redirect_uri per flow

Revision ID: 20260702_oauth_pkce_redirect_uri
Revises: 20260702_google_integrations
Create Date: 2026-07-02 12:00:00.000000+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260702_oauth_pkce_redirect_uri"
down_revision: Union[str, None] = "20260702_google_integrations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "oauth_pkce_states",
        sa.Column("redirect_uri", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("oauth_pkce_states", "redirect_uri")
