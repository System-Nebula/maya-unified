"""Parse Apple Music DJ mix albums from public album pages."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from maya_feeds.youtube_setlist import split_artist_title

_ALBUM_URL_RE = re.compile(
    r"music\.apple\.com/[^/]+/album/[^/]+/(\d+)",
    re.IGNORECASE,
)
_JSON_LD_RE = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_TRACK_ATTR_RE = re.compile(
    r'data-track-id="(\d+)"[^>]*data-position="(\d+)"[^>]*data-duration="(\d+)"[^>]*data-title="([^"]*)"',
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)
_LINK_RE = re.compile(r'href="(https?://[^"]+)"', re.IGNORECASE)


@dataclass
class ParsedAppleEntry:
    position: int
    start_seconds: int | None
    end_seconds: int | None
    label: str
    artist: str | None
    title: str | None
    track_id: str
    duration_seconds: int | None = None
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedAppleSet:
    album_id: str
    title: str
    container_url: str
    entries: list[ParsedAppleEntry]
    linked_urls: list[str] = field(default_factory=list)
    attrs: dict[str, Any] = field(default_factory=dict)


def extract_album_id(url: str) -> str | None:
    match = _ALBUM_URL_RE.search(url or "")
    return match.group(1) if match else None


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\\u0026", "&")).strip()


def _parse_json_ld(html: str) -> dict[str, Any]:
    for block in _JSON_LD_RE.findall(html or ""):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") in ("MusicAlbum", "MusicPlaylist"):
            return data
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("@type") in ("MusicAlbum", "MusicPlaylist"):
                    return item
    return {}


def _parse_title(html: str, json_ld: dict[str, Any]) -> str:
    if json_ld.get("name"):
        return _clean_text(str(json_ld["name"]))
    match = _TITLE_RE.search(html or "")
    if match:
        return _clean_text(match.group(1))
    return "Apple Music mix"


def _entries_from_json_ld(json_ld: dict[str, Any]) -> list[ParsedAppleEntry]:
    tracks = json_ld.get("track") or []
    if not isinstance(tracks, list):
        return []

    entries: list[ParsedAppleEntry] = []
    offset = 0
    for item in tracks:
        if not isinstance(item, dict):
            continue
        title = _clean_text(str(item.get("name") or ""))
        if not title:
            continue
        position = int(item.get("position") or len(entries) + 1)
        duration = _parse_duration(item.get("duration"))
        track_url = str(item.get("url") or "")
        track_id = _track_id_from_url(track_url) or f"pos{position}"
        artist, parsed_title = split_artist_title(title)
        start = offset
        end = offset + duration if duration else None
        if duration:
            offset += duration
        entries.append(
            ParsedAppleEntry(
                position=position,
                start_seconds=start,
                end_seconds=end,
                label=title,
                artist=artist,
                title=parsed_title or title,
                track_id=track_id,
                duration_seconds=duration,
                attrs={"mix_context": True},
            )
        )
    return entries


def _entries_from_attrs(html: str) -> list[ParsedAppleEntry]:
    entries: list[ParsedAppleEntry] = []
    offset = 0
    for match in _TRACK_ATTR_RE.finditer(html or ""):
        track_id = match.group(1)
        position = int(match.group(2))
        duration = int(match.group(3))
        title = _clean_text(match.group(4))
        artist, parsed_title = split_artist_title(title)
        start = offset
        end = offset + duration if duration else None
        offset += duration
        entries.append(
            ParsedAppleEntry(
                position=position,
                start_seconds=start,
                end_seconds=end,
                label=title,
                artist=artist,
                title=parsed_title or title,
                track_id=track_id,
                duration_seconds=duration or None,
                attrs={"mix_context": True},
            )
        )
    return entries


def _parse_duration(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if text.startswith("PT") and text.endswith("S"):
        body = text[2:-1]
        if "M" in body:
            minutes, seconds = body.split("M", 1)
            return int(minutes) * 60 + int(seconds or 0)
        return int(body or 0)
    try:
        return int(float(text))
    except ValueError:
        return None


def _track_id_from_url(url: str) -> str | None:
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(url)
    track_q = parse_qs(parsed.query).get("i")
    if track_q and track_q[0].isdigit():
        return track_q[0]
    path = parsed.path.rstrip("/")
    if not path:
        return None
    tail = path.rsplit("/", 1)[-1]
    return tail if tail.isdigit() else None


def _extract_linked_urls(html: str) -> list[str]:
    from urllib.parse import parse_qs, urlparse

    out: list[str] = []
    seen: set[str] = set()
    for raw in _LINK_RE.findall(html or ""):
        if "music.apple.com" in raw:
            continue
        parsed = urlparse(raw.rstrip(".,)"))
        host = (parsed.netloc or "").lower()
        if "youtube.com" in host or host == "youtu.be":
            vid = (parse_qs(parsed.query).get("v") or [None])[0]
            if vid:
                canonical = f"{parsed.scheme}://{parsed.netloc}/watch?v={vid}"
            else:
                canonical = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
        else:
            canonical = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
        if canonical not in seen:
            seen.add(canonical)
            out.append(canonical)
    return out


def parse_apple_music_html(url: str, html: str) -> ParsedAppleSet | None:
    album_id = extract_album_id(url)
    if not album_id:
        return None

    json_ld = _parse_json_ld(html)
    entries = _entries_from_json_ld(json_ld)
    if not entries:
        entries = _entries_from_attrs(html)
    if not entries:
        return None

    title = _parse_title(html, json_ld)
    linked = _extract_linked_urls(html)
    return ParsedAppleSet(
        album_id=album_id,
        title=title,
        container_url=url.split("?")[0],
        entries=entries,
        linked_urls=linked,
        attrs={"mix_context": True, "json_ld": json_ld} if json_ld else {"mix_context": True},
    )
