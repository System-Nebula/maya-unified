"""Discogs ontology enrichment for the music play resolver.

Maya's enrichment pipeline canonicalises music metadata against the Discogs
property graph. For ``/play`` resolve, we want the *videos* edge from a
master release — Discogs masters carry a ``videos[]`` array that links to
the canonical YouTube uploads for each track on the release. We hand those
candidates to the RadioPlayer so it can cycle through them when the first
embed is blocked by the uploader.

This module is intentionally tiny and dependency-light:
  - anonymous Discogs API by default (60 req/min/IP)
  - optional ``DISCOGS_TOKEN`` for authenticated calls (240 req/min)
  - in-process LRU cache so repeated /play calls don't burn rate limit
  - all network failures degrade silently to "no videos" rather than 5xx
"""

from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass
from typing import Optional

import httpx

from maya_contracts import DiscogsRef, VideoRef

logger = logging.getLogger(__name__)

USER_AGENT = "maya-public/0.1 (+https://github.com/maya-platform)"
API_BASE = "https://api.discogs.com"
DISCOGS_WEB_MASTER = "https://www.discogs.com/master/{master_id}"

_YT_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|embed/|v/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)


def _extract_youtube_id(url: str) -> Optional[str]:
    m = _YT_ID_RE.search(url)
    return m.group(1) if m else None


def _embed_url(video_id: str) -> str:
    return (
        f"https://www.youtube.com/embed/{video_id}"
        f"?enablejsapi=1&modestbranding=1&rel=0&playsinline=1"
    )


def _watch_url(video_id: str) -> str:
    return f"https://youtu.be/{video_id}"


@dataclass(frozen=True)
class DiscogsMaster:
    master_id: int
    title: str
    year: Optional[int]
    main_release: Optional[int]
    artists: list[str]
    videos: list[VideoRef]

    def ref(self) -> DiscogsRef:
        return DiscogsRef(
            master_id=self.master_id,
            release_id=self.main_release,
            url=DISCOGS_WEB_MASTER.format(master_id=self.master_id),
            year=self.year,
        )


class DiscogsClient:
    """Thread-safe Discogs API client with simple in-memory cache."""

    def __init__(
        self,
        *,
        token: Optional[str] = None,
        timeout: float = 4.0,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self._token = token or os.getenv("DISCOGS_TOKEN")
        self._timeout = timeout
        self._client = client
        self._cache: dict[int, Optional[DiscogsMaster]] = {}
        self._lock = threading.Lock()

    def _headers(self) -> dict[str, str]:
        h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if self._token:
            h["Authorization"] = f"Discogs token={self._token}"
        return h

    def _http(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return httpx.Client(timeout=self._timeout, headers=self._headers())

    def fetch_master(self, master_id: int) -> Optional[DiscogsMaster]:
        """Fetch a Discogs master release; cache result (incl. failures)."""
        with self._lock:
            if master_id in self._cache:
                return self._cache[master_id]

        result: Optional[DiscogsMaster]
        try:
            owns_client = self._client is None
            client = self._http()
            try:
                resp = client.get(f"{API_BASE}/masters/{master_id}")
                resp.raise_for_status()
                data = resp.json()
            finally:
                if owns_client:
                    client.close()
            result = _parse_master(master_id, data)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("discogs master fetch failed id=%s err=%s", master_id, exc)
            result = None

        with self._lock:
            self._cache[master_id] = result
        return result


def _parse_master(master_id: int, data: dict) -> DiscogsMaster:
    raw_videos = data.get("videos") or []
    videos: list[VideoRef] = []
    seen: set[str] = set()
    for entry in raw_videos:
        uri = entry.get("uri") or ""
        video_id = _extract_youtube_id(uri)
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)
        videos.append(
            VideoRef(
                youtube_id=video_id,
                title=entry.get("title") or None,
                duration_seconds=_coerce_duration(entry.get("duration")),
                embed_url=_embed_url(video_id),
                watch_url=_watch_url(video_id),
                source="discogs",
            )
        )

    return DiscogsMaster(
        master_id=master_id,
        title=data.get("title") or "",
        year=_coerce_int(data.get("year")),
        main_release=_coerce_int(data.get("main_release")),
        artists=[a.get("name", "") for a in (data.get("artists") or [])],
        videos=videos,
    )


def _coerce_int(value) -> Optional[int]:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_duration(value) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Process-wide default client. Tests/services that need to inject a stub can
# do so by constructing their own DiscogsClient and passing it explicitly.
_default_client: Optional[DiscogsClient] = None
_default_lock = threading.Lock()


def default_client() -> DiscogsClient:
    global _default_client
    with _default_lock:
        if _default_client is None:
            _default_client = DiscogsClient()
        return _default_client
