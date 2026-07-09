"""Link browser capture pages to music DJ set graph nodes."""

from __future__ import annotations

from maya_graph.music.primitives import DIM_SEMANTIC, EDGE_DERIVED_FROM
from maya_graph.projector import link, upsert_node


async def link_capture_to_set(
    conn,
    *,
    capture_id: str,
    set_key: str,
    url: str | None = None,
) -> None:
    """Edge: browser page —derived_from→ music dj_set."""
    page_node_id = await upsert_node(
        conn,
        domain="browser",
        domain_id=capture_id,
        node_type="page",
        label=url or capture_id,
        slug=capture_id[:8],
        description=url,
        attrs={"url": url, "capture_type": "tracklist"},
    )
    set_node_id = await upsert_node(
        conn,
        domain="music",
        domain_id=set_key,
        node_type="dj_set",
        label=set_key,
        slug=set_key.replace(":", "-")[:32],
        description=url,
        attrs={"linked_from_capture": capture_id},
    )
    await link(
        conn,
        page_node_id,
        set_node_id,
        edge_type=EDGE_DERIVED_FROM,
        dimension=DIM_SEMANTIC,
        evidence={"capture_id": capture_id, "url": url},
    )
