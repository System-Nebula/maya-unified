"""Image director session persistence.

Revision ID: 20260706_image_sessions
Revises: 20260704_image_jobs_corr_idx
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260706_image_sessions"
down_revision: Union[str, None] = "20260704_image_jobs_corr_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS image_sessions (
            id VARCHAR PRIMARY KEY,
            operator_id VARCHAR,
            discord_user_id VARCHAR,
            discord_channel_id VARCHAR,
            active_version_id VARCHAR,
            state JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_image_sessions_operator_id ON image_sessions (operator_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_image_sessions_discord_user_id ON image_sessions (discord_user_id)"
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_image_sessions_operator_updated
          ON image_sessions (operator_id, updated_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_image_sessions_discord_channel
          ON image_sessions (discord_user_id, discord_channel_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS image_sessions")
