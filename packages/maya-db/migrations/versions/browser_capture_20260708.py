"""Browser capture tables — durable event log + transactional outbox.

Revision ID: 20260708_browser_capture
Revises: 20260707_music_ontology

asyncpg constraint: exactly ONE SQL statement per op.execute() call.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260708_browser_capture"
down_revision: Union[str, None] = "20260707_music_ontology"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS captures (
            capture_id uuid PRIMARY KEY,
            content_hash text NOT NULL UNIQUE,
            capture_type text NOT NULL,
            url text NOT NULL,
            title text,
            reader_text text,
            selection text,
            tags jsonb NOT NULL DEFAULT '[]',
            metadata jsonb NOT NULL DEFAULT '{}',
            assets jsonb NOT NULL DEFAULT '[]',
            operator_id uuid REFERENCES operator_users(id) ON DELETE SET NULL,
            client_captured_at double precision NOT NULL,
            received_at timestamptz NOT NULL DEFAULT now(),
            processed_at timestamptz
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_captures_url ON captures (url)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_captures_type ON captures (capture_type)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS browser_capture_outbox (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            capture_id uuid NOT NULL REFERENCES captures(capture_id) ON DELETE CASCADE,
            payload jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            processed_at timestamptz
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_browser_capture_outbox_pending
        ON browser_capture_outbox (created_at)
        WHERE processed_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS browser_capture_outbox")
    op.execute("DROP TABLE IF EXISTS captures")
