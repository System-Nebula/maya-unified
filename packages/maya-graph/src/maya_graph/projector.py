"""Ontology graph projector — upsert helpers and pure similarity utilities.

Ported from private lib/sources/ontology/media_projector.py (public-safe subset).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator, Mapping

SHARED_DOMAIN = "shared"
FACET_TYPES = ("genre", "creator", "franchise", "studio", "year")


def normalize_key(value: str) -> str:
    """Stable, case/punct-insensitive key for a facet (genre, creator, …)."""
    value = value.strip().lower()
    value = value.replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def jaccard_edges(
    membership: Mapping[str, Iterable[str]],
    *,
    threshold: float = 0.3,
    min_shared: int = 1,
) -> Iterator[tuple[str, str, float, list[str]]]:
    """Yield (a, b, weight, shared_facets) for every title pair over the threshold."""
    sets = {k: set(v) for k, v in membership.items() if v}
    ids = sorted(sets)
    for i, a in enumerate(ids):
        sa = sets[a]
        for b in ids[i + 1 :]:
            sb = sets[b]
            shared = sa & sb
            if len(shared) < min_shared:
                continue
            union = sa | sb
            weight = len(shared) / len(union)
            if weight >= threshold:
                yield a, b, round(weight, 4), sorted(shared)


async def upsert_node(
    conn,
    *,
    domain: str,
    domain_id: str,
    node_type: str,
    label: str,
    slug: str | None = None,
    description: str | None = None,
    attrs: dict | None = None,
) -> str:
    """Upsert an ontology node; returns UUID."""
    return await conn.fetchval(
        """
        INSERT INTO ontology_node (domain, domain_id, node_type, label, slug, description, attrs)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (domain, domain_id, node_type) DO UPDATE SET
            label = EXCLUDED.label,
            slug = COALESCE(EXCLUDED.slug, ontology_node.slug),
            description = COALESCE(EXCLUDED.description, ontology_node.description),
            attrs = ontology_node.attrs || EXCLUDED.attrs,
            updated_at = now()
        RETURNING id
        """,
        domain,
        str(domain_id),
        node_type,
        label,
        slug,
        description,
        json.dumps(attrs or {}),
    )


async def upsert_artist_node(
    conn,
    *,
    slug: str,
    label: str,
    attrs: dict | None = None,
) -> str:
    """Upsert a music-domain artist node."""
    return await upsert_node(
        conn,
        domain="music",
        domain_id=slug,
        node_type="artist",
        label=label,
        slug=slug,
        attrs=attrs,
    )


async def upsert_attribute_node(
    conn,
    *,
    node_type: str,
    key: str,
    label: str | None = None,
) -> str:
    """Upsert a shared facet node (genre/creator/franchise/...). Returns UUID."""
    norm = normalize_key(key)
    return await conn.fetchval(
        """
        INSERT INTO ontology_node (domain, domain_id, node_type, label, slug, attrs)
        VALUES ($1, $2, $3, $4, $2, '{}')
        ON CONFLICT (domain, domain_id, node_type) DO UPDATE SET
            label = EXCLUDED.label,
            updated_at = now()
        RETURNING id
        """,
        SHARED_DOMAIN,
        norm,
        node_type,
        label or key,
    )


async def link(
    conn,
    source_id: str,
    target_id: str,
    *,
    edge_type: str,
    dimension: str = "semantic",
    weight: float = 1.0,
    confidence: float = 1.0,
    evidence: dict | None = None,
) -> None:
    """Upsert an ontology edge (idempotent on the full PK)."""
    await conn.execute(
        """
        INSERT INTO ontology_edge (source_id, target_id, edge_type, dimension, weight, confidence, evidence)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (source_id, target_id, edge_type, dimension) DO UPDATE SET
            weight = EXCLUDED.weight,
            confidence = EXCLUDED.confidence,
            evidence = EXCLUDED.evidence
        """,
        source_id,
        target_id,
        edge_type,
        dimension,
        weight,
        confidence,
        json.dumps(evidence or {}),
    )
