"""Canonical ontology graph DDL — single source of truth for node/edge tables.

Used by gateway projectors, research graph_writer, and ingest enrichment flows.
Tables may live on MAYA_ONTOLOGY_DSN (often the same Postgres as maya_public).
"""

from __future__ import annotations

ONTOLOGY_NODE_DDL = """
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

ONTOLOGY_EDGE_DDL = """
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

ONTOLOGY_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS ix_oe_source ON ontology_edge (source_id, dimension, weight DESC);
CREATE INDEX IF NOT EXISTS ix_oe_target ON ontology_edge (target_id, dimension, weight DESC);
"""


async def ensure_ontology_schema(conn) -> None:
    """Create ontology_node/edge tables and indexes if missing."""
    await conn.execute(ONTOLOGY_NODE_DDL)
    await conn.execute(ONTOLOGY_EDGE_DDL)
    await conn.execute(ONTOLOGY_INDEX_DDL)
