"""Search adapter: wrap slskd-api into typed maya-contracts models.

No business logic beyond search + ranking. Uses env vars for config so
the same adapter works in gateway mode and CLI mode.
"""

from __future__ import annotations

import os
import time
from pathlib import PureWindowsPath
from typing import Optional

from maya_contracts import (
    QualityTier,
    SearchHit,
    SearchQuery,
    SearchResult,
    compute_quality_score,
    infer_quality_tier,
)

# ---------------------------------------------------------------------------
# Client bootstrap
# ---------------------------------------------------------------------------

_SLSKD_CLIENT = None


def _get_client():
    global _SLSKD_CLIENT
    if _SLSKD_CLIENT is not None:
        return _SLSKD_CLIENT

    from slskd_api import SlskdClient

    host = os.environ.get("SLSKD_HOST", "http://localhost:5030")
    api_key = os.environ.get("SLSKD_API_KEY")
    if not api_key:
        raise RuntimeError("SLSKD_API_KEY is not set (see .env.example)")
    _SLSKD_CLIENT = SlskdClient(host=host, api_key=api_key)
    return _SLSKD_CLIENT


# ---------------------------------------------------------------------------
# Path parsing helpers
# ---------------------------------------------------------------------------

_KNOWN_EXTS = {".flac", ".mp3", ".m4a", ".wav", ".aiff", ".aif", ".ogg", ".opus", ".wma"}


def _parse_filename_hints(path: str) -> dict:
    """Try to extract artist / album / title from a Soulseek share path.

    Typical patterns:
        Music\\Artist\\Album\\01 - Title.flac
        E:\\Music\\Artist\\Album\\Title.mp3
        Downloads\\Artist - Album\\01 Title.flac
    """
    pw = PureWindowsPath(path)
    parts = list(pw.parents)[::-1] if pw.parents else []
    stem = pw.stem

    result: dict[str, Optional[str]] = {
        "artist_hint": None,
        "album_hint": None,
        "title_hint": stem,
    }

    # Walk parents bottom-up, looking for meaningful dir names
    meaningful = [p for p in parts if p.name and p.name not in ("Music", "Downloads", "E:", "F:")]
    if len(meaningful) >= 2:
        result["artist_hint"] = meaningful[-2].name  # second-to-last meaningful dir
        result["album_hint"] = meaningful[-1].name  # immediate parent
    elif len(meaningful) == 1:
        result["album_hint"] = meaningful[-1].name

    # Clean track number prefixes from title
    import re
    match = re.match(r"^(\d+)[\s\.\-_]+(.+)$", stem)
    if match:
        result["title_hint"] = match.group(2).strip()

    return result


# ---------------------------------------------------------------------------
# Search API
# ---------------------------------------------------------------------------


def search_slskd(query: SearchQuery, wait_seconds: int = 15) -> SearchResult:
    """Execute a structured query against Soulseek via slskd.

    Returns typed SearchResult with ranked hits.
    """
    client = _get_client()
    text = query.to_slskd_text()
    t0 = time.time()

    # 1. Initiate search
    raw = client.searches.search_text(text)

    # search_text returns either a dict with "id" or the id directly
    search_id: str = ""
    if isinstance(raw, dict):
        search_id = raw.get("id", "")
    else:
        search_id = str(raw)

    # 2. Wait for results
    time.sleep(wait_seconds)

    # 3. Fetch responses
    state = client.searches.state(search_id, includeResponses=True)
    responses = state.get("responses", []) if isinstance(state, dict) else []

    # 4. Flatten + type
    hits: list[SearchHit] = []
    for resp in responses:
        username = resp.get("username", "?")
        for f in resp.get("files", []):
            filename: str = f.get("filename", "")
            ext = PureWindowsPath(filename).suffix.lower().lstrip(".")
            size: int = f.get("size", 0)
            is_locked: bool = f.get("isLocked", False)
            has_free: bool = f.get("hasFreeUploadSlot", False)
            queue: int = f.get("queueLength", 0)
            speed: Optional[int] = f.get("uploadSpeed")

            # Extension filter
            if query.format_filter:
                hit_tier = infer_quality_tier(ext, filename)
                # Only keep hits meeting or exceeding the requested tier
                if hit_tier and _tier_rank(hit_tier) < _tier_rank(query.format_filter):
                    continue

            # Size filter
            if query.min_size and size < query.min_size:
                continue
            if query.max_size and size > query.max_size:
                continue

            # User filter
            if query.user and username.lower() != query.user.lower():
                continue

            # Skip locked files
            if is_locked:
                continue

            # Extension filter (basic)
            if ext not in ("flac", "mp3", "m4a", "wav", "aiff", "ogg", "opus"):
                continue

            hints = _parse_filename_hints(filename)
            tier = infer_quality_tier(ext, filename) or QualityTier.UNKNOWN
            score = compute_quality_score(tier, has_free, queue)

            hit = SearchHit(
                username=username,
                filename=filename,
                size=size,
                extension=ext,
                is_locked=is_locked,
                has_free_slot=has_free,
                queue_length=queue,
                upload_speed=speed,
                quality_tier=tier,
                quality_score=score,
                **hints,
            )
            hits.append(hit)

    # 5. Sort by quality score descending
    hits.sort(key=lambda h: h.quality_score, reverse=True)

    elapsed = time.time() - t0
    total = len(hits)

    return SearchResult(
        query=query,
        hits=tuple(hits[: query.max_results]),
        total_hits=total,
        search_id=search_id,
        elapsed_seconds=elapsed,
    )


# ---------------------------------------------------------------------------
# Download API
# ---------------------------------------------------------------------------


def enqueue_download(
    username: str,
    filename: str,
    size: int,
) -> str | None:
    """Enqueue a single file download on slskd.

    Returns the transfer ID on success, None on failure.
    """
    client = _get_client()
    payload = [
        {
            "filename": filename,
            "size": size,
            "startOffset": 0,
        }
    ]
    try:
        result = client.transfers.enqueue(username, payload)
        # The API returns a dict or list; extract an ID if possible
        if isinstance(result, dict):
            return str(result.get("id", ""))
        if isinstance(result, list) and result:
            return str(result[0].get("id", "")) if isinstance(result[0], dict) else str(result[0])
        return str(result) if result else None
    except Exception as exc:
        return None


def get_downloads() -> list[dict]:
    """Return all current downloads from slskd."""
    client = _get_client()
    return client.transfers.get_all_downloads()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _tier_rank(tier: QualityTier) -> int:
    """Higher = better."""
    ranks = {
        QualityTier.LOSSLESS_24BIT: 100,
        QualityTier.LOSSLESS: 90,
        QualityTier.LOSSLESS_CD: 85,
        QualityTier.HIGH: 60,
        QualityTier.STANDARD: 45,
        QualityTier.AAC_256: 40,
        QualityTier.LOW: 20,
        QualityTier.UNKNOWN: 10,
    }
    return ranks.get(tier, 10)
