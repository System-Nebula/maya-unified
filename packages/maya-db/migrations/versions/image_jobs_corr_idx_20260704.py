"""Index image_jobs metadata corr_id and trace_id for imagine correlation."""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260704_image_jobs_corr_idx"
down_revision: Union[str, None] = "20260705_merge_google_operator"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_image_jobs_metadata_corr_id
          ON image_jobs ((metadata->>'corr_id'))
          WHERE metadata->>'corr_id' IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_image_jobs_metadata_trace_id
          ON image_jobs ((metadata->>'trace_id'))
          WHERE metadata->>'trace_id' IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_image_jobs_metadata_trace_id")
    op.execute("DROP INDEX IF EXISTS ix_image_jobs_metadata_corr_id")
