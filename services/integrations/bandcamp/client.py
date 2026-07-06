"""Bandcamp fan profile and wishlist HTTP client."""

from __future__ import annotations

import html
import json
import re
import time
from typing import Any

import httpx

_FAN_PAGE_RE = re.compile(
    r'id="pagedata"[^>]*\sdata-blob="([^"]+)"',
    re.IGNORECASE,
)
_WISHLIST_URL = "https://bandcamp.com/api/fancollection/1/wishlist_items"
_USER_AGENT = "Maya-Unified/1.0 (+https://github.com/system-nebula/maya-unified)"


class BandcampError(Exception):
    """Base error for Bandcamp integration failures."""


class BandcampProfileNotFound(BandcampError):
    pass


class BandcampWishlistPrivate(BandcampError):
    pass


class BandcampRateLimited(BandcampError):
    pass


def _parse_pagedata(html_text: str) -> dict[str, Any]:
    match = _FAN_PAGE_RE.search(html_text)
    if not match:
        raise BandcampError("Could not parse Bandcamp profile page")
    raw = html.unescape(match.group(1))
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BandcampError("Invalid Bandcamp profile data") from exc


def resolve_fan_profile(username: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    """Fetch fan_id and wishlist metadata for a public Bandcamp username."""
    slug = username.strip().lstrip("@")
    if not slug:
        raise BandcampError("Bandcamp username is required")

    url = f"https://bandcamp.com/{slug}"
    owns = client is None
    http = client or httpx.Client(timeout=20.0, follow_redirects=True, headers={"User-Agent": _USER_AGENT})
    try:
        resp = http.get(url)
        if resp.status_code == 404:
            raise BandcampProfileNotFound(f"Bandcamp profile not found: {slug}")
        if resp.status_code == 429:
            raise BandcampRateLimited("Bandcamp rate limit exceeded — try again in a few minutes")
        resp.raise_for_status()
        blob = _parse_pagedata(resp.text)
    except httpx.HTTPError as exc:
        raise BandcampError(f"Bandcamp request failed: {exc}") from exc
    finally:
        if owns:
            http.close()

    fan_data = blob.get("fan_data") or {}
    fan_id = fan_data.get("fan_id")
    if not fan_id:
        raise BandcampProfileNotFound(f"Bandcamp profile not found: {slug}")

    wishlist_data = blob.get("wishlist_data") or {}
    return {
        "username": slug,
        "fan_id": int(fan_id),
        "display_name": str(fan_data.get("name") or slug),
        "wishlist_count": int(wishlist_data.get("item_count") or 0),
        "wishlist_private": bool(wishlist_data.get("private")),
        "last_token": str(wishlist_data.get("last_token") or ""),
    }


def _older_than_token(*, offset: int) -> str:
    ts = int(time.time())
    if offset <= 0:
        return f"{ts}::a::"
    return f"{ts}::a:{offset}:"


def fetch_wishlist_items(
    fan_id: int,
    *,
    count: int = 20,
    offset: int = 0,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Fetch a page of wishlist items from Bandcamp's internal API."""
    payload = {
        "fan_id": fan_id,
        "older_than_token": _older_than_token(offset=offset),
        "count": max(1, min(count, 2000)),
    }
    owns = client is None
    http = client or httpx.Client(timeout=20.0, follow_redirects=True, headers={"User-Agent": _USER_AGENT})
    try:
        resp = http.post(_WISHLIST_URL, json=payload, headers={"Content-Type": "application/json"})
        if resp.status_code == 429:
            raise BandcampRateLimited("Bandcamp rate limit exceeded — try again in a few minutes")
        if resp.status_code in (403, 401):
            raise BandcampWishlistPrivate("This Bandcamp wishlist is private")
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPError as exc:
        raise BandcampError(f"Bandcamp wishlist request failed: {exc}") from exc
    finally:
        if owns:
            http.close()

    items = data.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def normalize_wishlist_item(raw: dict[str, Any]) -> dict[str, str]:
    title = str(
        raw.get("album_title")
        or raw.get("title")
        or raw.get("item_title")
        or "Unknown title"
    ).strip()
    artist = str(
        raw.get("band_name")
        or raw.get("artist")
        or raw.get("item_artist")
        or "Unknown artist"
    ).strip()
    url = str(raw.get("item_url") or raw.get("url") or "").strip()
    item_type = str(raw.get("item_type") or raw.get("tralbum_type") or "album").strip()
    if item_type == "t":
        item_type = "track"
    elif item_type == "a":
        item_type = "album"
    art = str(raw.get("item_art_url") or raw.get("art_url") or "").strip()
    if not art:
        art_id = raw.get("item_art_id") or raw.get("art_id")
        if art_id:
            art = f"https://f4.bcbits.com/img/a{art_id}_16.jpg"
    return {"title": title, "artist": artist, "url": url, "item_type": item_type, "art": art}
