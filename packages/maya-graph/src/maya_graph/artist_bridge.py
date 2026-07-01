"""Bridge follow-graph persons to music ontology artists."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ArtistBridgeMatch:
    person_slug: str
    ontology_artist_id: str
    ontology_slug: str
    label: str
    confidence: float


def slugify(name: str) -> str:
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


async def match_person_to_ontology(
    person_slug: str,
    *,
    dsn: str | None = None,
) -> Optional[ArtistBridgeMatch]:
    """Find a music/artist ontology node for a followed person slug."""
    dsn = dsn or os.getenv("MAYA_ONTOLOGY_DSN")
    if not dsn or not person_slug:
        return None
    try:
        import asyncpg
    except ImportError:
        return None

    slug = slugify(person_slug)
    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow(
            """
            SELECT id, slug, label
            FROM ontology_node
            WHERE domain = 'music'
              AND node_type = 'artist'
              AND (slug = $1 OR domain_id = $1)
            LIMIT 1
            """,
            slug,
        )
        if row is None:
            row = await conn.fetchrow(
                """
                SELECT id, slug, label
                FROM ontology_node
                WHERE domain = 'music'
                  AND node_type = 'artist'
                  AND lower(label) = lower($1)
                LIMIT 1
                """,
                person_slug.replace("-", " "),
            )
    finally:
        await conn.close()

    if row is None:
        return None
    return ArtistBridgeMatch(
        person_slug=slug,
        ontology_artist_id=str(row["id"]),
        ontology_slug=row["slug"] or slug,
        label=row["label"],
        confidence=0.9 if row["slug"] == slug else 0.7,
    )


async def list_followed_artist_slugs(
    person_slugs: list[str],
    *,
    dsn: str | None = None,
) -> list[ArtistBridgeMatch]:
    out: list[ArtistBridgeMatch] = []
    for slug in person_slugs:
        match = await match_person_to_ontology(slug, dsn=dsn)
        if match:
            out.append(match)
    return out
