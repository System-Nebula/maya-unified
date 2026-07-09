"""Central music URL handler — fetch, parse, and normalize DJ set lists."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from maya_feeds.tracklist.filter import classify_tracklist_url, is_tracklist_url
from maya_feeds.tracklist.normalize import parsed_to_tracklist_resolved
from maya_feeds.tracklist.protocol import TracklistPlatform
from maya_feeds.tracklist.registry import get_tracklist_parser
from services.music.set_bridge import tracklist_to_resolved_set
from services.music.set_types import (
    PLATFORM_1001TL,
    PLATFORM_APPLE,
    PLATFORM_YOUTUBE,
    ResolvedSet,
    SetEntry,
)
from services.music.url_cache import FetchTrace, cache_get, cache_set, normalize_url

logger = logging.getLogger(__name__)

__all__ = [
    "PLATFORM_1001TL",
    "PLATFORM_APPLE",
    "PLATFORM_YOUTUBE",
    "ResolvedSet",
    "SetEntry",
    "detect_platform",
    "fetch_and_parse_document",
    "fetch_and_parse_url",
    "index_music_url",
    "index_music_url_sync",
    "is_tracklist_url",
]


def detect_platform(url: str) -> str | None:
    platform = classify_tracklist_url(url)
    return platform.value if platform else None


async def _fetch_html(url: str) -> str:
    cached = cache_get("html", url)
    if cached is not None:
        return cached
    from maya_spider.http import AsyncRateLimiter, FailurePolicy, create_async_client, request_with_retry

    limiter = AsyncRateLimiter(1.0)
    headers = {"User-Agent": "Maya/1.0 (+https://github.com/maya-unified)"}

    async with create_async_client(timeout=25.0, follow_redirects=True, headers=headers) as client:
        await limiter.acquire()

        async def _request():
            return await client.get(url)

        resp = await request_with_retry(_request, failure_policy=FailurePolicy(retry_attempts=3))
        text = resp.text
    cache_set("html", url, text)
    return text


def _fetch_youtube_info(url: str) -> dict[str, Any] | None:
    cached = cache_get("ytdlp", url)
    if cached is not None:
        return cached
    try:
        import yt_dlp

        from services.discord.youtube_patch import _cookie_opts
    except Exception:
        logger.debug("yt-dlp unavailable for set fetch", exc_info=True)
        return None

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        **_cookie_opts(),
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        logger.warning("youtube set fetch failed for %s", url, exc_info=True)
        return None
    if info:
        cache_set("ytdlp", url, info)
    return info


async def _fetch_youtube_comments_text(video_id: str) -> str | None:
    cached = cache_get("yt_comments", video_id)
    if cached is not None:
        return cached
    try:
        from maya_contracts import CommentWindow
        from maya_feeds.youtube import YouTubeAdapter

        adapter = YouTubeAdapter()
        try:
            fetched = await adapter.fetch_comments(video_id, CommentWindow.T1W)
        finally:
            await adapter._http.aclose()
        if not fetched.comments:
            return None
        text = fetched.comments[0].text
        if text:
            cache_set("yt_comments", video_id, text)
        return text or None
    except Exception:
        logger.debug("youtube comment fetch failed for %s", video_id, exc_info=True)
        return None


async def _enrich_youtube_info_from_comments(url: str, info: dict[str, Any]) -> dict[str, Any]:
    from maya_feeds.youtube_setlist import extract_youtube_video_id, parse_tracklist_lines

    description = str(info.get("description") or "")
    if parse_tracklist_lines(description, duration_seconds=info.get("duration")):
        return info
    video_id = str(info.get("id") or extract_youtube_video_id(url) or "").strip()
    if not video_id:
        return info
    comment_text = await _fetch_youtube_comments_text(video_id)
    if not comment_text:
        return info
    enriched = dict(info)
    enriched["comment_tracklist"] = comment_text
    return enriched


def _document_cache_hit(url: str, platform: TracklistPlatform) -> bool:
    if platform == TracklistPlatform.YOUTUBE:
        return cache_get("ytdlp", url) is not None
    return cache_get("html", url) is not None


async def _fetch_document(url: str, platform: TracklistPlatform) -> Any | None:
    if platform == TracklistPlatform.YOUTUBE:
        info = await asyncio.to_thread(_fetch_youtube_info, url)
        if info is None:
            return None
        return await _enrich_youtube_info_from_comments(url, info)
    return await _fetch_html(url)


def parse_document(url: str, document: Any) -> ResolvedSet | None:
    """Parse a pre-fetched document (HTML or yt-dlp dict) into a ResolvedSet."""
    parser = get_tracklist_parser(url)
    if parser is None:
        return None
    parsed = parser.parse(url, document)
    if parsed is None:
        return None
    return tracklist_to_resolved_set(parsed_to_tracklist_resolved(parsed))


async def fetch_and_parse_document(url: str, document: Any) -> ResolvedSet | None:
    return parse_document(url, document)


async def fetch_and_parse_url(url: str) -> ResolvedSet | None:
    from services.tracing import corr_span

    parser = get_tracklist_parser(url)
    if parser is None:
        return None
    cache_hit = _document_cache_hit(url, parser.platform)
    with corr_span(
        "music.fetch_document",
        platform=parser.platform.value,
        cache_hit=cache_hit,
    ):
        document = await _fetch_document(url, parser.platform)
    if document is None:
        return None
    with corr_span("music.tracklist_parse", parser=parser.__class__.__name__) as span:
        result = parse_document(url, document)
        if result is not None:
            span.set_attribute("entry_count", len(result.entries))
            span.set_attribute("title", result.title)
        return result


async def index_music_url(
    url: str,
    *,
    correlate: bool = True,
    ingest: bool = True,
) -> ResolvedSet | None:
    """Fetch and parse a music URL; optionally merge linked cross-source sets."""
    from services.tracing import corr_span

    seed = (url or "").strip()
    with corr_span("music.url_index", url=seed, platform=detect_platform(seed)) as span:
        trace = FetchTrace(seed_url=seed)
        fetched: list[str] = []
        platforms: list[str] = []

        async def _fetch_traced(target: str) -> ResolvedSet | None:
            canonical = normalize_url(target)
            if canonical and canonical not in fetched:
                fetched.append(canonical)
            platform = detect_platform(target)
            if platform and platform not in platforms:
                platforms.append(platform)
            return await fetch_and_parse_url(target)

        primary = await _fetch_traced(seed)
        if primary is None:
            return None

        if correlate and primary.linked_sets:
            from services.music.set_correlate import correlate_sets

            result = primary
            for ref in primary.linked_sets:
                if not ref.url or normalize_url(ref.url) == normalize_url(seed):
                    continue
                try:
                    linked = await _fetch_traced(ref.url)
                except Exception:
                    logger.debug("linked set fetch failed for %s", ref.url, exc_info=True)
                    continue
                if linked is not None:
                    result = correlate_sets(result, linked)
        else:
            result = primary

        trace.fetched_urls = fetched
        trace.platforms = platforms
        trace.correlated_at = time.time()
        result = ResolvedSet(
            set_key=result.set_key,
            title=result.title,
            container_url=result.container_url,
            container_schema=result.container_schema,
            entries=result.entries,
            linked_sets=result.linked_sets,
            attrs={**result.attrs, "fetch_trace": trace.to_dict()},
        )
        span.set_attribute("set_key", result.set_key)
        span.set_attribute("entry_count", len(result.entries))

        if ingest:
            try:
                from services.music.set_ingest import ingest_set

                await ingest_set(result)
            except Exception:
                logger.warning("set ingest failed for %s", url, exc_info=True)

        return result


def index_music_url_sync(
    url: str,
    *,
    correlate: bool = True,
    ingest: bool = True,
) -> ResolvedSet | None:
    from services.async_bridge import run_sync

    return run_sync(index_music_url(url, correlate=correlate, ingest=ingest), timeout=30)
