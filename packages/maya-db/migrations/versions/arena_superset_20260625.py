"""Restore arena multi-signal voting columns and aux tables.

Revision ID: 20260625_arena_superset
Revises: 20260624_research
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260625_arena_superset"
down_revision: Union[str, None] = "20260624_research"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE arena_candidates ADD COLUMN IF NOT EXISTS modality varchar(16) NOT NULL DEFAULT 'tts'"
    )
    op.execute("ALTER TABLE arena_candidates ADD COLUMN IF NOT EXISTS variant_key varchar(255)")
    op.execute("ALTER TABLE arena_candidates ADD COLUMN IF NOT EXISTS config jsonb")
    op.execute(
        "ALTER TABLE arena_candidates ADD COLUMN IF NOT EXISTS rating_deviation double precision DEFAULT 350"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidates_modality_rating ON arena_candidates (modality, rating)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidates_modality_active "
        "ON arena_candidates (modality, is_active, rating)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidates_provider_model ON arena_candidates (provider, voice_id)"
    )

    op.execute(
        "ALTER TABLE arena_battles ADD COLUMN IF NOT EXISTS modality varchar(16) NOT NULL DEFAULT 'tts'"
    )
    op.execute("ALTER TABLE arena_battles ADD COLUMN IF NOT EXISTS input_payload jsonb")
    op.execute("ALTER TABLE arena_battles ADD COLUMN IF NOT EXISTS extra_data jsonb")
    op.execute("ALTER TABLE arena_battles ADD COLUMN IF NOT EXISTS started_at timestamptz")
    for col in ("votes_a", "votes_b", "votes_tie", "total_votes"):
        op.execute(
            f"""
            DO $$ BEGIN
              IF (SELECT data_type FROM information_schema.columns
                  WHERE table_name='arena_battles' AND column_name='{col}') = 'integer' THEN
                ALTER TABLE arena_battles ALTER COLUMN {col} TYPE double precision USING {col}::double precision;
              END IF;
            END $$
            """
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_battles_modality_created ON arena_battles (modality, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_battles_candidates ON arena_battles (candidate_a_id, candidate_b_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS arena_votes (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
            battle_id uuid NOT NULL REFERENCES arena_battles (id),
            user_id varchar(255) NOT NULL,
            username varchar(255),
            choice varchar(8) NOT NULL,
            signal_type varchar(32) NOT NULL DEFAULT 'explicit_vote',
            reaction varchar(32),
            weight double precision NOT NULL DEFAULT 1.0,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_arena_votes_battle_id ON arena_votes (battle_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_arena_votes_user_id ON arena_votes (user_id)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_votes_battle_user_signal "
        "ON arena_votes (battle_id, user_id, signal_type)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS arena_artifacts (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
            battle_id uuid NOT NULL REFERENCES arena_battles (id),
            candidate_id uuid NOT NULL REFERENCES arena_candidates (id),
            slot varchar(8) NOT NULL,
            artifact_type varchar(16) NOT NULL,
            url text,
            local_path text,
            mime_type varchar(128),
            extra_data jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_arena_artifacts_battle_id ON arena_artifacts (battle_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_arena_artifacts_candidate_id ON arena_artifacts (candidate_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_artifacts_battle_slot ON arena_artifacts (battle_id, slot)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS arena_sessions (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
            battle_id uuid NOT NULL REFERENCES arena_battles (id),
            started_by varchar(255) NOT NULL,
            channel_id varchar(64),
            guild_id varchar(64),
            message_id varchar(64) UNIQUE,
            is_active boolean DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_arena_sessions_battle_id ON arena_sessions (battle_id)")


def downgrade() -> None:
    op.drop_table("arena_sessions")
    op.drop_table("arena_artifacts")
    op.drop_table("arena_votes")
    op.drop_index("ix_battles_modality_created", table_name="arena_battles")
    op.drop_index("ix_battles_candidates", table_name="arena_battles")
    for col in ("votes_a", "votes_b", "votes_tie", "total_votes"):
        op.alter_column(
            "arena_battles",
            col,
            type_=sa.Integer(),
            existing_type=sa.Float(),
            postgresql_using=f"{col}::integer",
        )
    op.drop_column("arena_battles", "started_at")
    op.drop_column("arena_battles", "extra_data")
    op.drop_column("arena_battles", "input_payload")
    op.drop_column("arena_battles", "modality")
    op.drop_index("ix_candidates_modality_active", table_name="arena_candidates")
    op.drop_index("ix_candidates_modality_rating", table_name="arena_candidates")
    op.drop_index("ix_candidates_provider_model", table_name="arena_candidates")
    op.drop_column("arena_candidates", "rating_deviation")
    op.drop_column("arena_candidates", "config")
    op.drop_column("arena_candidates", "variant_key")
    op.drop_column("arena_candidates", "modality")
