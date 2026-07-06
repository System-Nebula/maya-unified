"""Music ontology hybrid tier — relational identity tables + graph DDL.

Revision ID: 20260707_music_ontology
Revises: 20260706_director_workflows

Creates:
- ontology_node / ontology_edge (inline IF NOT EXISTS copies of the canonical
  DDL in maya_graph.ontology_schema — do not import maya-graph in a migration).
  These are shared cross-domain tables and may already exist via the runtime
  ``ensure_ontology_schema`` path; every statement is idempotent.
- music_* relational tables (genre, artist, track, track_artist, release,
  release_track, platform_link).

asyncpg constraint: exactly ONE SQL statement per op.execute() call.

downgrade() drops ONLY the music_* tables. ontology_node/ontology_edge are
shared with other domains (research graph_writer, projectors) and must never
be dropped here.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260707_music_ontology"
down_revision: Union[str, None] = "20260706_director_workflows"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- shared ontology graph (source of truth: maya_graph/ontology_schema.py) ---
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ontology_node (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            domain text NOT NULL,
            domain_id text NOT NULL,
            node_type text NOT NULL,
            label text NOT NULL,
            slug text,
            description text,
            attrs jsonb NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (domain, domain_id, node_type)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ontology_edge (
            source_id uuid NOT NULL,
            target_id uuid NOT NULL,
            edge_type text NOT NULL,
            dimension text NOT NULL DEFAULT 'semantic',
            weight float NOT NULL DEFAULT 1.0,
            confidence float NOT NULL DEFAULT 1.0,
            evidence jsonb NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (source_id, target_id, edge_type, dimension)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_oe_source ON ontology_edge (source_id, dimension, weight DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_oe_target ON ontology_edge (target_id, dimension, weight DESC)"
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_on_music_canonical_work
        ON ontology_node (domain, node_type, label)
        WHERE domain = 'music' AND node_type IN ('canonical_work', 'recording')
        """
    )

    # --- music relational tier (FK dependency order) ---
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS music_genre (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name text NOT NULL,
            slug varchar(255) NOT NULL,
            parent_id uuid REFERENCES music_genre(id) ON DELETE SET NULL,
            beatport_id integer,
            source varchar(32) NOT NULL DEFAULT 'beatport',
            attrs jsonb NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_music_genre_slug UNIQUE (slug),
            CONSTRAINT uq_music_genre_beatport_id UNIQUE (beatport_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_music_genre_parent ON music_genre (parent_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS music_artist (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name text NOT NULL,
            sort_name text,
            artist_type varchar(32) NOT NULL DEFAULT 'artist',
            country_code varchar(8),
            is_group boolean NOT NULL DEFAULT false,
            aliases jsonb NOT NULL DEFAULT '[]',
            attrs jsonb NOT NULL DEFAULT '{}',
            graph_node_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_music_artist_name_lower ON music_artist (lower(name))"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS music_track (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            title text NOT NULL,
            base_title text,
            remix_name text,
            remix_artist text,
            version_type varchar(32),
            duration_seconds integer,
            isrc varchar(32),
            canonical_fingerprint varchar(255) NOT NULL,
            cluster_key varchar(64),
            bpm double precision,
            key_camelot varchar(8),
            primary_artist_id uuid REFERENCES music_artist(id) ON DELETE SET NULL,
            genre_id uuid REFERENCES music_genre(id) ON DELETE SET NULL,
            sub_genre_id uuid REFERENCES music_genre(id) ON DELETE SET NULL,
            canonical_work_key varchar(64),
            graph_node_id uuid,
            attrs jsonb NOT NULL DEFAULT '{}',
            enriched_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_music_track_fingerprint UNIQUE (canonical_fingerprint)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_music_track_cluster ON music_track (cluster_key)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_music_track_isrc ON music_track (isrc)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_music_track_work_key ON music_track (canonical_work_key)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_music_track_primary_artist ON music_track (primary_artist_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS music_track_artist (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            track_id uuid NOT NULL REFERENCES music_track(id) ON DELETE CASCADE,
            artist_id uuid NOT NULL REFERENCES music_artist(id) ON DELETE CASCADE,
            role varchar(32) NOT NULL DEFAULT 'primary',
            billing_order integer NOT NULL DEFAULT 0,
            CONSTRAINT uq_music_track_artist UNIQUE (track_id, artist_id, role, billing_order)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_music_track_artist_artist ON music_track_artist (artist_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS music_release (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            title text NOT NULL,
            release_type varchar(32),
            label text,
            catalog_number varchar(64),
            release_date date,
            primary_artist_id uuid REFERENCES music_artist(id) ON DELETE SET NULL,
            attrs jsonb NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS music_release_track (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            release_id uuid NOT NULL REFERENCES music_release(id) ON DELETE CASCADE,
            track_id uuid NOT NULL REFERENCES music_track(id) ON DELETE CASCADE,
            disc_number integer,
            track_number integer,
            CONSTRAINT uq_music_release_track UNIQUE (release_id, track_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS music_platform_link (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_type varchar(32) NOT NULL,
            entity_id uuid NOT NULL,
            platform varchar(32) NOT NULL,
            external_id varchar(255),
            url text NOT NULL,
            confidence double precision NOT NULL DEFAULT 1.0,
            source varchar(64) NOT NULL DEFAULT 'manual',
            attrs jsonb NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_music_platform_ext UNIQUE (platform, external_id),
            CONSTRAINT uq_music_platform_entity UNIQUE (entity_type, entity_id, platform, external_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_music_platform_link_entity ON music_platform_link (entity_type, entity_id)"
    )


def downgrade() -> None:
    # music tables only — NEVER drop shared ontology_node/ontology_edge here.
    op.execute("DROP TABLE IF EXISTS music_release_track")
    op.execute("DROP TABLE IF EXISTS music_release")
    op.execute("DROP TABLE IF EXISTS music_track_artist")
    op.execute("DROP TABLE IF EXISTS music_platform_link")
    op.execute("DROP TABLE IF EXISTS music_track")
    op.execute("DROP TABLE IF EXISTS music_artist")
    op.execute("DROP TABLE IF EXISTS music_genre")
