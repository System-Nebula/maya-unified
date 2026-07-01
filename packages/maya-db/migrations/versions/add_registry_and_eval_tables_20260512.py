"""add registry and eval tables

Revision ID: 20260512_195810
Revises: a511a30e9f86
Create Date: 2026-05-12 19:58:10.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260512_195810"
down_revision: Union[str, None] = "a511a30e9f86"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_releases",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("capability_family", sa.String(length=32), nullable=False),
        sa.Column("modality_in", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("modality_out", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("base_model", sa.String(length=255), nullable=True),
        sa.Column("quantization", sa.String(length=64), nullable=True),
        sa.Column("runtime", sa.String(length=64), nullable=True),
        sa.Column("license", sa.String(length=64), nullable=True),
        sa.Column("artifacts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("eval_status", sa.String(length=32), server_default="discovered", nullable=False),
        sa.Column("publisher_claims", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_releases_slug", "model_releases", ["slug"])
    op.create_index("ix_model_releases_eval_status", "model_releases", ["eval_status"])

    op.create_table(
        "eval_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("model_release_id", sa.String(length=36), nullable=False),
        sa.Column("eval_suite", sa.String(length=128), nullable=False),
        sa.Column("eval_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("artifact_paths", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["model_release_id"], ["model_releases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_runs_model_release_id", "eval_runs", ["model_release_id"])
    op.create_index("ix_eval_runs_status", "eval_runs", ["status"])

    op.add_column(
        "arena_candidates",
        sa.Column("model_release_id", sa.String(length=36), nullable=True),
    )
    op.create_index("ix_arena_candidates_model_release_id", "arena_candidates", ["model_release_id"])
    op.create_foreign_key(
        "fk_arena_candidates_model_release_id",
        "arena_candidates",
        "model_releases",
        ["model_release_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_arena_candidates_model_release_id", "arena_candidates", type_="foreignkey")
    op.drop_index("ix_arena_candidates_model_release_id", table_name="arena_candidates")
    op.drop_column("arena_candidates", "model_release_id")

    op.drop_index("ix_eval_runs_status", table_name="eval_runs")
    op.drop_index("ix_eval_runs_model_release_id", table_name="eval_runs")
    op.drop_table("eval_runs")

    op.drop_index("ix_model_releases_eval_status", table_name="model_releases")
    op.drop_index("ix_model_releases_slug", table_name="model_releases")
    op.drop_table("model_releases")
