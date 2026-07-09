"""Music reaction table for operator likes/stars/hearts on tracks and sets."""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260709_music_reaction"
down_revision: Union[str, None] = "20260708_browser_capture"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS music_reaction (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            operator_id uuid NOT NULL,
            entity_type varchar(32) NOT NULL,
            entity_key varchar(255) NOT NULL,
            reaction varchar(16) NOT NULL,
            source_url text,
            attrs jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_music_reaction_operator_entity
                UNIQUE (operator_id, entity_type, entity_key, reaction)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_music_reaction_entity ON music_reaction (entity_type, entity_key)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS music_reaction")
