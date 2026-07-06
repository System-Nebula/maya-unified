"""Ontology-first play resolution for the public gateway.

Tries the music ontology (``services.music.ontology`` → MusicQueryBroker)
first; a confident hit returns ``matched_via="ontology"`` with an
``OntologyRef`` attached. Misses, low confidence, timeouts, and any failure
fall through to the demo-catalog resolver unchanged — the ontology tier must
never make ``/play/resolve`` worse than v1.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Awaitable, Callable, Optional

from maya_contracts import (
    PlayResolveRequest,
    PlayResolveResponse,
    TrackInfo,
    VideoRef,
)

from maya_gateway.services.play_resolve import (
    _youtube_embed,
    _youtube_thumb,
    _youtube_watch,
    resolve as demo_resolve,
)

logger = logging.getLogger(__name__)

_ONTOLOGY_BUDGET_S = 8.0

_YT_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|embed/)|youtu\.be/)([A-Za-z0-9_-]{6,})"
)


def _extract_youtube_id(url: str | None) -> Optional[str]:
    if not url:
        return None
    match = _YT_ID_RE.search(url)
    return match.group(1) if match else None


async def _default_resolver(query: str):
    # services.* lives at the repo root; available when maya-gateway routes
    # are mounted inside apps/gateway (same pattern as slskd_search).
    from services.music.ontology import resolve_for_play

    return await resolve_for_play(query)


def _track_from_resolution(resolved) -> TrackInfo:
    videos: list[VideoRef] = []
    stream_url: Optional[str] = None
    watch_url: Optional[str] = None
    artwork_url: Optional[str] = None

    yt_ref = next((r for r in resolved.source_refs if r.schema_id == "yt"), None)
    video_id = (
        yt_ref.external_id
        if yt_ref is not None and yt_ref.external_id
        else _extract_youtube_id(resolved.play_url)
    )
    if video_id:
        stream_url = _youtube_embed(video_id)
        watch_url = _youtube_watch(video_id)
        artwork_url = _youtube_thumb(video_id)
        videos.append(
            VideoRef(
                youtube_id=video_id,
                title=resolved.title,
                embed_url=stream_url,
                watch_url=watch_url,
                source="ontology",
            )
        )
    else:
        watch_url = resolved.play_url

    return TrackInfo(
        track_id=f"ontology:{resolved.work_key or resolved.title}",
        title=resolved.title,
        artist=resolved.artist or "Unknown",
        stream_url=stream_url,
        watch_url=watch_url,
        artwork_url=artwork_url,
        videos=videos,
        ontology=resolved.ontology,
        source_refs=list(resolved.source_refs),
    )


async def resolve_with_ontology(
    req: PlayResolveRequest,
    *,
    resolver: Callable[[str], Awaitable] | None = None,
    fallback: Callable[[PlayResolveRequest], PlayResolveResponse] = demo_resolve,
) -> PlayResolveResponse:
    """Broker-first resolve; falls back to the demo catalog on any miss."""
    resolve_fn = resolver or _default_resolver
    resolved = None
    try:
        resolved = await asyncio.wait_for(
            resolve_fn(req.query), timeout=_ONTOLOGY_BUDGET_S
        )
    except Exception as exc:  # noqa: BLE001 — ontology tier is best-effort
        logger.warning("ontology play resolve failed for %r: %s", req.query, exc)
        resolved = None

    if resolved is None:
        return fallback(req)

    return PlayResolveResponse(
        matched_via="ontology",
        query=req.query,
        zone=req.zone,
        tracks=[_track_from_resolution(resolved)],
        explanation=f"Matched canonical work {resolved.work_key or resolved.title!r} "
        f"(confidence {resolved.confidence:.2f}).",
    )
