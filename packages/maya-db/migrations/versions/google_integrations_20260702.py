"""google integrations: connections, identities, oauth pkce states

Revision ID: 20260702_google_integrations
Revises: 20260701_operator_users
Create Date: 2026-07-02 00:00:00.000000+00:00
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260702_google_integrations"
down_revision: Union[str, None] = "20260701_operator_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "operator_google_identities",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("google_sub", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
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
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["operator_id"], ["operator_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("google_sub"),
    )
    op.create_index(
        "ix_operator_google_identities_operator_id",
        "operator_google_identities",
        ["operator_id"],
    )

    op.create_table(
        "google_connections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("google_sub", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column(
            "connected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(["operator_id"], ["operator_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_google_connections_operator_id", "google_connections", ["operator_id"])
    op.create_index("ix_google_connections_google_sub", "google_connections", ["google_sub"])
    op.create_index("ix_google_connections_status", "google_connections", ["status"])

    op.create_table(
        "oauth_pkce_states",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("state", sa.String(length=128), nullable=False),
        sa.Column("verifier", sa.String(length=256), nullable=False),
        sa.Column("flow", sa.String(length=16), nullable=False),
        sa.Column("requested_scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("operator_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_token", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["operator_id"], ["operator_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state"),
    )
    op.create_index("ix_oauth_pkce_states_state", "oauth_pkce_states", ["state"])


def downgrade() -> None:
    op.drop_index("ix_oauth_pkce_states_state", table_name="oauth_pkce_states")
    op.drop_table("oauth_pkce_states")
    op.drop_index("ix_google_connections_status", table_name="google_connections")
    op.drop_index("ix_google_connections_google_sub", table_name="google_connections")
    op.drop_index("ix_google_connections_operator_id", table_name="google_connections")
    op.drop_table("google_connections")
    op.drop_index("ix_operator_google_identities_operator_id", table_name="operator_google_identities")
    op.drop_table("operator_google_identities")
