"""Supporting index for the canonical_work/recording node types.

Does NOT redefine ontology_node/ontology_edge — canonical DDL lives in
``maya_graph.ontology_schema.ensure_ontology_schema``. This only adds an index
scoped to music-graph node types, idempotently.
"""

from __future__ import annotations

from maya_graph.ontology_schema import ensure_ontology_schema


async def ensure_music_entity_schema(conn) -> None:
    await ensure_ontology_schema(conn)
    await conn.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_on_music_canonical_work
        ON ontology_node (domain, node_type, label)
        WHERE domain = 'music' AND node_type IN ('canonical_work', 'recording')
        """
    )
