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


def _track_from_set_entry(resolved_set, entry) -> TrackInfo:
    video_id = _extract_youtube_id(resolved_set.container_url)
    stream_url = _youtube_embed(video_id) if video_id else resolved_set.container_url
    watch_url = _youtube_watch(video_id) if video_id else resolved_set.container_url
    artwork_url = _youtube_thumb(video_id) if video_id else None
    duration = None
    if entry.end_seconds is not None:
        duration = max(0, entry.end_seconds - entry.start_seconds)
    return TrackInfo(
        track_id=f"{resolved_set.set_key}:{entry.position}",
        title=entry.label,
        artist=entry.artist or "Unknown",
        stream_url=stream_url,
        watch_url=watch_url,
        artwork_url=artwork_url,
        duration_seconds=duration,
        source_refs=list(entry.source_refs),
        start_offset_seconds=entry.start_seconds,
        end_offset_seconds=entry.end_seconds,
        set_key=resolved_set.set_key,
        set_position=entry.position,
        play_mode=entry.play_mode,
        ontology=None,
    )


async def resolve_with_ontology(
    req: PlayResolveRequest,
    *,
    resolver: Callable[[str], Awaitable] | None = None,
    fallback: Callable[[PlayResolveRequest], PlayResolveResponse] = demo_resolve,
) -> PlayResolveResponse:
    """Broker-first resolve; falls back to the demo catalog on any miss."""
    query = (req.query or "").strip()
    if query.startswith(("http://", "https://")):
        try:
            from services.music.url_handler import detect_platform, index_music_url

            if detect_platform(query):
                resolved_set = await asyncio.wait_for(
                    index_music_url(query, ingest=False, correlate=True),
                    timeout=_ONTOLOGY_BUDGET_S,
                )
                if resolved_set is not None and resolved_set.entries:
                    tracks = [_track_from_set_entry(resolved_set, entry) for entry in resolved_set.entries]
                    return PlayResolveResponse(
                        matched_via="setlist",
                        query=req.query,
                        zone=req.zone,
                        tracks=tracks,
                        explanation=(
                            f"Parsed {len(tracks)} tracks from {resolved_set.container_schema} set "
                            f"{resolved_set.set_key}."
                        ),
                    )
        except Exception as exc:  # noqa: BLE001
            logger.debug("setlist play resolve skipped for %r: %s", query, exc)

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
