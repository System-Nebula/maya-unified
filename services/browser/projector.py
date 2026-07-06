"""Ontology projection for browser captures."""

from __future__ import annotations

from typing import Any

from maya_graph.projector import link, upsert_node


async def project_browser_capture(
    conn,
    *,
    capture_id: str,
    url: str,
    title: str,
    capture_type: str,
    assets: list[dict[str, Any]],
) -> str:
    """Upsert page node + saved_from edge; returns page node UUID."""
    page_node_id = await upsert_node(
        conn,
        domain="browser",
        domain_id=capture_id,
        node_type="page",
        label=title or url,
        slug=capture_id[:8],
        description=url,
        attrs={
            "url": url,
            "capture_type": capture_type,
            "asset_count": len(assets),
        },
    )

    chrome_node_id = await upsert_node(
        conn,
        domain="browser",
        domain_id="chrome",
        node_type="source",
        label="Chrome",
        slug="chrome",
        attrs={"kind": "browser_extension"},
    )

    await link(
        conn,
        page_node_id,
        chrome_node_id,
        edge_type="saved_from",
        dimension="provenance",
        evidence={"capture_id": capture_id},
    )
    return page_node_id
