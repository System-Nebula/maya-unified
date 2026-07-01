"""Persist research runs to ontology graph (domain=research)."""

from __future__ import annotations

import json
import os
from typing import Any

from maya_contracts import ResearchReport
from maya_graph.ontology_schema import ensure_ontology_schema


async def persist_to_ontology(
    run_id: str,
    report: ResearchReport,
    *,
    sources: list[dict[str, Any]] | None = None,
) -> None:
    dsn = os.getenv("MAYA_ONTOLOGY_DSN")
    if not dsn:
        return
    try:
        import asyncpg
    except ImportError:
        return

    conn = await asyncpg.connect(dsn)
    try:
        await ensure_ontology_schema(conn)
        node_id = await conn.fetchval(
            """
            INSERT INTO ontology_node (domain, domain_id, node_type, label, slug, attrs)
            VALUES ('research', $1, 'ResearchNode', $2, $1, $3::jsonb)
            ON CONFLICT (domain, domain_id, node_type)
            DO UPDATE SET
              label = EXCLUDED.label,
              attrs = ontology_node.attrs || EXCLUDED.attrs,
              updated_at = now()
            RETURNING id
            """,
            run_id,
            report.title[:255],
            json.dumps(
                {
                    "brief": report.brief,
                    "summary": report.executive_summary,
                    "artifact_sections": len(report.sections),
                    "uncovered_aspects": report.uncovered_aspects,
                }
            ),
        )

        topic_slug = _slugify(report.title)
        topic_id = await conn.fetchval(
            """
            INSERT INTO ontology_node (domain, domain_id, node_type, label, slug, attrs)
            VALUES ('research', $1, 'Topic', $2, $1, '{}'::jsonb)
            ON CONFLICT (domain, domain_id, node_type)
            DO UPDATE SET label = EXCLUDED.label, updated_at = now()
            RETURNING id
            """,
            f"topic:{topic_slug}",
            report.title[:255],
        )
        await conn.execute(
            """
            INSERT INTO ontology_edge (source_id, target_id, edge_type, dimension, weight, confidence)
            VALUES ($1, $2, 'COVERS', 'semantic', 1.0, 1.0)
            ON CONFLICT (source_id, target_id, edge_type, dimension) DO NOTHING
            """,
            node_id,
            topic_id,
        )

        for src in sources or []:
            url = src.get("url") or ""
            if not url:
                continue
            src_id = await conn.fetchval(
                """
                INSERT INTO ontology_node (domain, domain_id, node_type, label, slug, attrs)
                VALUES ('research', $1, 'SourceNode', $2, $1, $3::jsonb)
                ON CONFLICT (domain, domain_id, node_type)
                DO UPDATE SET attrs = ontology_node.attrs || EXCLUDED.attrs, updated_at = now()
                RETURNING id
                """,
                f"source:{_slugify(url)[:120]}",
                (src.get("title") or url)[:255],
                json.dumps(
                    {
                        "url": url,
                        "credibility_score": src.get("credibility_score", 0.5),
                    }
                ),
            )
            await conn.execute(
                """
                INSERT INTO ontology_edge (source_id, target_id, edge_type, dimension, weight, confidence)
                VALUES ($1, $2, 'CITES', 'semantic', $3, 1.0)
                ON CONFLICT (source_id, target_id, edge_type, dimension) DO NOTHING
                """,
                node_id,
                src_id,
                float(src.get("credibility_score") or 0.5),
            )
    finally:
        await conn.close()


def _slugify(value: str) -> str:
    out = "".join(c if c.isalnum() else "-" for c in value.lower())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")[:120] or "research"
