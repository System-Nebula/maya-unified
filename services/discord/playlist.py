"""Expand album / playlist URLs into individual track queries for playback."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger("maya-unified.discord.playlist")

_URL_RE = re.compile(r"^https?://", re.I)


@dataclass
class PlaylistExpansion:
    """A resolved album / playlist: an ordered list of (query, title) tracks."""

    title: str
    tracks: list[tuple[str, str]] = field(default_factory=list)
    artist: str | None = None
    playlist_id: str | None = None
    video_ids: list[str | None] = field(default_factory=list)


def is_url(value: str) -> bool:
    return bool(_URL_RE.match((value or "").strip()))


def _playlist_id(url: str) -> str | None:
    from urllib.parse import parse_qs, urlparse

    values = parse_qs(urlparse(url).query).get("list") or []
    raw = (values[0] if values else "").strip()
    return raw or None


def _video_id(entry: dict, track_url: str) -> str | None:
    raw = str(entry.get("id") or "").strip()
    if len(raw) == 11:
        return raw
    from urllib.parse import parse_qs, urlparse

    vid = (parse_qs(urlparse(track_url).query).get("v") or [None])[0]
    if vid:
        return str(vid)
    if "youtu.be/" in track_url:
        return track_url.rsplit("/", 1)[-1][:11]
    return None


def expand_playlist(url: str) -> PlaylistExpansion | None:
    """Return per-track queries for an album/playlist URL, else None.

    ``None`` means "not a multi-track URL" — the caller should queue the raw input
    directly (a single-track URL, or a plain search query). yt-dlp resolves Bandcamp
    albums, YouTube playlists, SoundCloud sets, etc. natively. The URL is only ever
    handed to the yt-dlp Python API here (never split/tokenized), so odd-looking
    links cannot break parsing.
    """
    target = (url or "").strip()
    if not is_url(target):
        return None

    try:
        import yt_dlp

        from services.discord.youtube_patch import _cookie_opts
    except Exception:  # noqa: BLE001 - yt-dlp/settings unavailable
        log.debug("yt-dlp unavailable for playlist expansion", exc_info=True)
        return None

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        **_cookie_opts(),
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(target, download=False)
    except Exception:  # noqa: BLE001 - best-effort; fall back to raw queue
        log.warning("playlist expansion failed for %s", target, exc_info=True)
        return None

    if not info:
        return None
    entries = [e for e in (info.get("entries") or []) if e]
    if not entries:
        return None  # single-track URL — queue as-is

    tracks: list[tuple[str, str]] = []
    video_ids: list[str | None] = []
    for entry in entries:
        track_url = str(entry.get("webpage_url") or entry.get("url") or "").strip()
        if not track_url and entry.get("id"):
            vid = str(entry["id"]).strip()
            extractor = str(
                entry.get("ie_key") or entry.get("extractor") or info.get("extractor") or ""
            ).lower()
            if "youtube" in extractor or (len(vid) == 11 and vid.isalnum()):
                track_url = f"https://www.youtube.com/watch?v={vid}"
        if not track_url:
            continue
        title = str(entry.get("title") or "").strip()
        tracks.append((track_url, title))
        video_ids.append(_video_id(entry, track_url))

    if not tracks:
        return None

    album_title = str(info.get("title") or "").strip()
    artist = (
        str(info.get("artist") or info.get("album_artist") or info.get("uploader") or info.get("channel") or "")
        .strip()
        or None
    )
    log.info("expanded %s -> %d tracks (%s)", target, len(tracks), album_title[:60])
    return PlaylistExpansion(
        title=album_title,
        tracks=tracks,
        artist=artist,
        playlist_id=_playlist_id(target),
        video_ids=video_ids,
    )
