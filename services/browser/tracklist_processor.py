"""Process browser-captured tracklist HTML into the music ontology."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from maya_feeds.tracklist.filter import is_tracklist_url
from services.browser.object_store import fetch_capture_asset
from services.browser.projector import project_browser_capture
from services.music.capture_link import link_capture_to_set
from services.music.url_cache import cache_set
from services.music.url_handler import index_music_url

log = logging.getLogger(__name__)


def _parse_assets(assets: list[dict[str, Any]] | str | None) -> list[dict[str, Any]]:
    if assets is None:
        return []
    if isinstance(assets, str):
        return json.loads(assets)
    return list(assets)


async def _load_html_asset(
    assets: list[dict[str, Any]],
    *,
    http_client: httpx.AsyncClient,
) -> str | None:
    for asset in assets:
        if asset.get("kind") != "html":
            continue
        key = asset.get("key")
        if not key:
            continue
        raw = await fetch_capture_asset(http_client, key)
        return raw.decode("utf-8", errors="replace")
    return None


async def process_tracklist_capture(
    conn,
    *,
    capture_id: str,
    url: str,
    title: str,
    assets: list[dict[str, Any]] | str | None,
    http_client: httpx.AsyncClient,
) -> dict[str, Any] | None:
    """Parse captured tracklist HTML, index into graph, link page → dj_set."""
    if not is_tracklist_url(url):
        return None

    parsed_assets = _parse_assets(assets)
    html = await _load_html_asset(parsed_assets, http_client=http_client)
    if not html:
        log.warning("tracklist capture %s missing html asset", capture_id)
        return None

    cache_set("html", url, html)

    resolved = await index_music_url(url, correlate=True, ingest=True)
    if resolved is None:
        log.warning("tracklist index failed for capture %s url=%s", capture_id, url)
        return None

    await project_browser_capture(
        conn,
        capture_id=capture_id,
        url=url,
        title=title,
        capture_type="tracklist",
        assets=parsed_assets,
    )
    await link_capture_to_set(conn, capture_id=capture_id, set_key=resolved.set_key, url=url)

    return {
        "set_key": resolved.set_key,
        "entry_count": len(resolved.entries),
        "fetch_trace": resolved.attrs.get("fetch_trace"),
    }
