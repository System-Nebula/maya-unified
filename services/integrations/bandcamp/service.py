"""Bandcamp wishlist service — resolve username and list items."""

from __future__ import annotations

import re
from typing import Any

import httpx

from services.integrations.bandcamp.client import (
    BandcampError,
    BandcampProfileNotFound,
    BandcampRateLimited,
    BandcampWishlistPrivate,
    fetch_wishlist_items,
    normalize_wishlist_item,
    resolve_fan_profile,
)
from services.integrations.bandcamp.config import default_username


def _schedule_wishlist_ingest(items: list[dict[str, Any]]) -> None:
    if not items:
        return
    try:
        from services.async_bridge import schedule_coro
        from services.music.ontology import ingest_bandcamp_items

        schedule_coro(ingest_bandcamp_items(items))
    except Exception:  # noqa: BLE001 — feed hook must not break wishlist UX
        pass

_BANDCAMP_USER_RE = re.compile(
    r"(?:https?://)?(?:www\.)?bandcamp\.com/(?!album|track|tag|discover|search|music|merch)([A-Za-z0-9_-]+)(?:/(?:wishlist|collection|following|followers))?/?",
    re.I,
)
_RESERVED = frozenset(
    {"album", "track", "tag", "discover", "search", "music", "merch", "help", "login", "signup"}
)

_GENRE_ALIASES: dict[str, list[str]] = {
    "dnb": [
        "dnb",
        "drum and bass",
        "drum n bass",
        "drum & bass",
        "drum'n'bass",
        "jungle",
        "neurofunk",
        "breakcore",
        "liquid funk",
        "halftime",
    ],
    "jungle": ["jungle", "ragga jungle", "breakbeat jungle"],
    "techno": ["techno", "minimal techno", "industrial techno"],
    "house": ["house", "deep house", "tech house"],
}


def parse_bandcamp_username(text: str) -> str | None:
    """Extract a fan username from a Bandcamp profile or wishlist URL."""
    raw = (text or "").strip()
    if not raw:
        return None
    match = _BANDCAMP_USER_RE.search(raw)
    if not match:
        return None
    slug = match.group(1).strip().lstrip("@")
    if not slug or slug.lower() in _RESERVED:
        return None
    return slug


def resolve_username(
    settings: dict[str, Any] | None,
    *,
    hint: str = "",
    explicit: str = "",
) -> str:
    """Resolve Bandcamp username from settings, env, explicit param, or URL hint."""
    if explicit:
        slug = str(explicit).strip().lstrip("@")
        if slug:
            return slug

    bandcamp = (settings or {}).get("bandcamp") if isinstance(settings, dict) else None
    if isinstance(bandcamp, dict):
        username = str(bandcamp.get("username") or "").strip()
        if username and bandcamp.get("enabled", True) is not False:
            return username

    env_user = default_username()
    if env_user:
        return env_user

    if hint:
        parsed = parse_bandcamp_username(hint)
        if parsed:
            return parsed

    return ""


def ensure_username_configured(operator_id: str | None, username: str) -> None:
    """Persist Bandcamp username when learned from a URL or tool call."""
    slug = (username or "").strip().lstrip("@")
    if not operator_id or not slug:
        return
    from services.voice.hub import hub

    hub.apply_settings_patch(
        {"bandcamp": {"enabled": True, "username": slug}},
        operator_id=str(operator_id),
    )


def expand_filter_keywords(filter_text: str) -> list[str]:
    raw = (filter_text or "").strip().lower()
    if not raw:
        return []
    if raw in _GENRE_ALIASES:
        return list(_GENRE_ALIASES[raw])
    keywords = [raw]
    for alias_list in _GENRE_ALIASES.values():
        if raw in alias_list:
            keywords.extend(alias_list)
            break
    return list(dict.fromkeys(keywords))


def item_matches_filter(item: dict[str, Any], keywords: list[str]) -> bool:
    if not keywords:
        return True
    hay = f"{item.get('title', '')} {item.get('artist', '')}".lower()
    return any(kw in hay for kw in keywords)


def is_bandcamp_wishlist_turn(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if parse_bandcamp_username(raw):
        return True
    tl = raw.lower()
    if "bandcamp" in tl and "wishlist" in tl:
        return True
    if "wishlist" in tl and any(w in tl for w in ("queue", "play", "dnb", "drum", "jungle")):
        return True
    return False


def bandcamp_playback_intent(text: str) -> bool:
    tl = (text or "").lower()
    return any(w in tl for w in ("queue", "play", "dnb", "drum", "jungle", "neurofunk", "breakcore"))


def list_wishlist(
    username: str,
    *,
    limit: int = 10,
    offset: int = 0,
    fetch_cap: int = 25,
) -> dict[str, Any]:
    """Return a slice of the fan's public wishlist."""
    slug = username.strip().lstrip("@")
    if not slug:
        raise BandcampError(
            "Bandcamp username not configured — set bandcamp.username in settings "
            "or MAYA_BANDCAMP_USERNAME"
        )

    cap = max(1, min(int(fetch_cap), 50))
    limit = max(1, min(int(limit), cap))
    offset = max(0, int(offset))

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        profile = resolve_fan_profile(slug, client=client)
        if profile.get("wishlist_private"):
            raise BandcampWishlistPrivate("This Bandcamp wishlist is private")

        raw_items = fetch_wishlist_items(
            profile["fan_id"],
            count=limit + offset if offset else limit,
            offset=offset,
            client=client,
        )

    items = [normalize_wishlist_item(item) for item in raw_items[:limit]]
    total = int(profile.get("wishlist_count") or len(items))

    _schedule_wishlist_ingest(items)

    return {
        "username": profile["username"],
        "display_name": profile.get("display_name") or profile["username"],
        "total_count": total,
        "offset": offset,
        "limit": limit,
        "items": items,
    }


def play_wishlist(
    username: str,
    *,
    filter_text: str = "",
    limit: int = 5,
) -> dict[str, Any]:
    """Filter wishlist items and build a merged dashboard playlist artifact."""
    from services.dashboard.player import build_playlist_artifact
    from services.discord.playlist import expand_playlist

    queue_limit = max(1, min(int(limit), 10))
    keywords = expand_filter_keywords(filter_text)
    catalog = list_wishlist(username, limit=50, fetch_cap=50)
    items = catalog.get("items") or []
    matches = [item for item in items if item_matches_filter(item, keywords)]

    if filter_text and not matches:
        sample = ", ".join(
            f"“{i.get('title', '?')}”" for i in items[:3]
        )
        return {
            "ok": False,
            "error": (
                f"No wishlist items matched filter “{filter_text}”. "
                f"First items include {sample or 'none fetched'}."
            ),
        }

    targets = matches[:queue_limit] if matches else items[:queue_limit]
    if not targets:
        return {"ok": False, "error": "Your Bandcamp wishlist is empty."}

    merged_tracks: list[dict[str, str]] = []
    queued_items: list[dict[str, str]] = []
    for item in targets:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        try:
            expansion = expand_playlist(url)
        except Exception:  # noqa: BLE001
            expansion = None
        artifact = build_playlist_artifact(url, expansion)
        item_art = (item.get("art") or "").strip()
        item_artist = (item.get("artist") or "").strip()
        for track in artifact.get("tracks") or []:
            if item_art and not track.get("art"):
                track["art"] = item_art
            if item_artist and not track.get("artist"):
                track["artist"] = item_artist
            merged_tracks.append(track)
        queued_items.append(
            {
                "title": item.get("title") or "",
                "artist": item.get("artist") or "",
                "url": url,
            }
        )

    if not merged_tracks:
        return {"ok": False, "error": "Could not resolve playable URLs from the wishlist."}

    filter_label = filter_text.strip() or "wishlist"
    playlist = {
        "type": "playlist",
        "title": f"Bandcamp {filter_label} ({catalog.get('username', username)})",
        "url": targets[0].get("url") or "",
        "tracks": merged_tracks,
    }
    noun = "track" if len(merged_tracks) == 1 else "tracks"
    titles = ", ".join(f"“{i['title']}”" for i in queued_items[:3])
    extra = f" and {len(queued_items) - 3} more" if len(queued_items) > 3 else ""
    message = (
        f"Queued {len(merged_tracks)} {noun} from your Bandcamp wishlist"
        f"{f' matching {filter_text}' if filter_text else ''}: {titles}{extra}."
    )
    _schedule_wishlist_ingest(queued_items)
    return {
        "ok": True,
        "message": message,
        "playlist": playlist,
        "queued": len(merged_tracks),
        "items": queued_items,
        "username": catalog.get("username"),
    }


def format_wishlist_speech(result: dict[str, Any]) -> str:
    """Build a speakable summary for voice output."""
    items = result.get("items") or []
    total = int(result.get("total_count") or 0)
    offset = int(result.get("offset") or 0)
    if not items:
        return "Your Bandcamp wishlist is empty."

    lines: list[str] = []
    for idx, item in enumerate(items, start=offset + 1):
        title = item.get("title") or "Unknown title"
        artist = item.get("artist") or "Unknown artist"
        lines.append(f"{idx}. “{title}” by {artist}")

    shown = len(items)
    if total > shown + offset:
        end = offset + shown
        header = f"Showing items {offset + 1} through {end} of {total} on your Bandcamp wishlist."
    elif total > shown:
        header = f"Showing {shown} of {total} items on your Bandcamp wishlist."
    else:
        header = f"Your Bandcamp wishlist has {total} item{'s' if total != 1 else ''}."

    return header + " " + ". ".join(lines) + "."


def connection_status(username: str) -> dict[str, Any]:
    """Probe whether a username resolves and return wishlist metadata."""
    slug = username.strip().lstrip("@")
    if not slug:
        return {"connected": False, "username": "", "wishlist_count": 0}

    try:
        profile = resolve_fan_profile(slug)
    except BandcampProfileNotFound:
        return {
            "connected": False,
            "username": slug,
            "wishlist_count": 0,
            "error": "profile not found",
        }
    except BandcampRateLimited:
        return {
            "connected": False,
            "username": slug,
            "wishlist_count": 0,
            "error": "rate limited",
        }
    except BandcampError as exc:
        return {
            "connected": False,
            "username": slug,
            "wishlist_count": 0,
            "error": str(exc),
        }

    return {
        "connected": True,
        "username": profile["username"],
        "display_name": profile.get("display_name") or profile["username"],
        "wishlist_count": int(profile.get("wishlist_count") or 0),
        "wishlist_private": bool(profile.get("wishlist_private")),
    }


__all__ = [
    "BandcampError",
    "BandcampProfileNotFound",
    "BandcampRateLimited",
    "BandcampWishlistPrivate",
    "bandcamp_playback_intent",
    "connection_status",
    "ensure_username_configured",
    "expand_filter_keywords",
    "format_wishlist_speech",
    "is_bandcamp_wishlist_turn",
    "item_matches_filter",
    "list_wishlist",
    "parse_bandcamp_username",
    "play_wishlist",
    "resolve_username",
]
