"""Research tables — runs, sources, sentiment bundles, topic embeddings.

Revision ID: 20260624_research
Revises: 20260609_knowledge
Create Date: 2026-06-24 00:00:00.000000+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260624_research"
down_revision: Union[str, None] = "20260609_knowledge"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "research_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("operator_id", sa.String(length=64), nullable=False, server_default="local"),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column("depth", sa.String(length=16), nullable=False, server_default="shallow"),
        sa.Column(
            "source_mask",
            postgresql.JSONB(),
            nullable=False,
            server_default='["web","reddit","local","graph"]',
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("plan", postgresql.JSONB(), nullable=True),
        sa.Column("plan_approved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("prior_research_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("prior_research", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("report", postgresql.JSONB(), nullable=True),
        sa.Column("artifact_id", sa.String(length=64), nullable=True),
        sa.Column("artifact_key", sa.String(length=512), nullable=True),
        sa.Column("progress", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("errors", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("discord_thread_id", sa.String(length=64), nullable=True),
        sa.Column("seed_urls", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("brief_embedding", sa.dialects.postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delta_mode", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("delta_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_runs_operator_id", "research_runs", ["operator_id"])
    op.create_index("ix_research_runs_status", "research_runs", ["status"])

    op.create_table(
        "research_sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("credibility_score", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("artifact_key", sa.String(length=512), nullable=True),
        sa.Column("operator_visited", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["research_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_sources_run_id", "research_sources", ["run_id"])

    op.create_table(
        "research_sentiments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subreddit", sa.String(length=128), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["research_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_sentiments_run_id", "research_sentiments", ["run_id"])

    op.create_table(
        "research_topic_embeddings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("embedding", sa.dialects.postgresql.ARRAY(sa.Float()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["research_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )

    op.create_table(
        "browser_history_embeddings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("embedding", sa.dialects.postgresql.ARRAY(sa.Float()), nullable=False),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url"),
    )
    op.create_index("ix_browser_history_embeddings_url", "browser_history_embeddings", ["url"])

    # Upgrade brief_embedding and topic embedding to vector type when pgvector is available
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
                ALTER TABLE research_runs
                    ALTER COLUMN brief_embedding TYPE vector(768)
                    USING brief_embedding::vector(768);
                ALTER TABLE research_topic_embeddings
                    ALTER COLUMN embedding TYPE vector(768)
                    USING embedding::vector(768);
                ALTER TABLE browser_history_embeddings
                    ALTER COLUMN embedding TYPE vector(768)
                    USING embedding::vector(768);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_table("browser_history_embeddings")
    op.drop_table("research_topic_embeddings")
    op.drop_table("research_sentiments")
    op.drop_table("research_sources")
    op.drop_table("research_runs")
