"""In-memory fetch cache and trajectory trace for music URL indexing."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

_DEFAULT_TTL_S = 3600.0

# kind -> normalized_url -> (expires_at, payload)
_cache: dict[str, dict[str, tuple[float, Any]]] = {}


@dataclass
class FetchTrace:
    """Provenance breadcrumb for a multi-hop set index."""

    seed_url: str
    fetched_urls: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    correlated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_url(url: str) -> str:
    """Canonicalize URL for cache keys (strip playlist params on YouTube)."""
    text = (url or "").strip()
    if not text:
        return text
    parsed = urlparse(text)
    host = (parsed.netloc or "").lower().removeprefix("www.")
    if "youtube.com" in host or host == "youtu.be":
        qs = parse_qs(parsed.query, keep_blank_values=True)
        vid = (qs.get("v") or [None])[0]
        if vid:
            clean_qs = urlencode({"v": vid})
            return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", clean_qs, ""))
    return text


def cache_get(kind: str, url: str) -> Any | None:
    key = normalize_url(url)
    bucket = _cache.get(kind)
    if not bucket:
        return None
    row = bucket.get(key)
    if row is None:
        return None
    expires_at, payload = row
    if time.time() >= expires_at:
        del bucket[key]
        return None
    return payload


def cache_set(kind: str, url: str, payload: Any, *, ttl_s: float = _DEFAULT_TTL_S) -> None:
    key = normalize_url(url)
    _cache.setdefault(kind, {})[key] = (time.time() + ttl_s, payload)


def cache_clear() -> None:
    """Drop all cached payloads (for tests)."""
    _cache.clear()
