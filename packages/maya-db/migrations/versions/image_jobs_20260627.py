"""Image job persistence for ComfyUI generation tracking.

Revision ID: 20260627_image_jobs
Revises: 20260626_image_workflows
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260627_image_jobs"
down_revision: Union[str, None] = "20260626_image_workflows"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS image_jobs (
            id VARCHAR PRIMARY KEY,
            user_id VARCHAR,
            provider_key VARCHAR NOT NULL,
            provider_job_id VARCHAR,
            status VARCHAR NOT NULL DEFAULT 'pending',
            mode VARCHAR NOT NULL,
            prompt TEXT NOT NULL,
            size VARCHAR,
            quality VARCHAR,
            mask_url VARCHAR,
            references JSONB DEFAULT '[]',
            output JSONB DEFAULT '{}',
            error TEXT,
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_image_jobs_user_id ON image_jobs (user_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_image_jobs_status_created ON image_jobs (status, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_image_jobs_provider_status ON image_jobs (provider_key, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_image_jobs_user_created ON image_jobs (user_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS image_jobs")
