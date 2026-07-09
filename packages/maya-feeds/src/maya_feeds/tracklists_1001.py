"""Parse DJ set tracklists from 1001tracklists.com pages."""

from __future__ import annotations

import html as html_module
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlparse

from maya_feeds.youtube_intel import timestamp_to_seconds
from maya_feeds.youtube_setlist import split_artist_title

_TRACKLIST_URL_RE = re.compile(
    r"1001tracklists\.com/tracklist/([a-z0-9]+)/",
    re.IGNORECASE,
)
_TRACK_ROW_RE = re.compile(
    r'<div[^>]*class="[^"]*tlpItem[^"]*"[^>]*>(.*?)</div>\s*</div>',
    re.DOTALL | re.IGNORECASE,
)
_TRACK_TIME_RE = re.compile(
    r'(?:data-track-time|trackTime)[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_TRACK_ARTIST_RE = re.compile(
    r'class="[^"]*trackValue[^"]*artist[^"]*"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_TRACK_TITLE_RE = re.compile(
    r'class="[^"]*trackValue[^"]*title[^"]*"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_LINK_RE = re.compile(r'href="(https?://[^"]+)"', re.IGNORECASE)
_JSON_LD_RE = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)


@dataclass
class Parsed1001Entry:
    position: int
    start_seconds: int | None
    end_seconds: int | None
    label: str
    artist: str | None
    title: str | None
    timestamp: str | None
    row_id: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class Parsed1001Set:
    tracklist_id: str
    title: str
    container_url: str
    entries: list[Parsed1001Entry]
    linked_urls: list[str] = field(default_factory=list)
    attrs: dict[str, Any] = field(default_factory=dict)


def extract_tracklist_id(url: str) -> str | None:
    match = _TRACKLIST_URL_RE.search(url or "")
    return match.group(1) if match else None


def _clean_html_text(text: str) -> str:
    value = re.sub(r"<[^>]+>", " ", text or "")
    value = html_module.unescape(unquote(value))
    return re.sub(r"\s+", " ", value).strip()


def _parse_timestamp(raw: str | None) -> tuple[str | None, int | None]:
    if not raw:
        return None, None
    ts = raw.strip()
    if not re.match(r"^\d{1,2}:\d{2}(?::\d{2})?$", ts):
        return None, None
    return ts, timestamp_to_seconds(ts)


def _extract_linked_urls(html: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for href in _LINK_RE.findall(html or ""):
        if "1001tracklists.com" in href:
            continue
        if href not in seen:
            seen.add(href)
            urls.append(href)
    return urls


def _parse_title(html: str) -> str:
    match = _TITLE_RE.search(html or "")
    if match:
        return _clean_html_text(match.group(1))
    return "1001tracklists set"


def _parse_json_ld(html: str) -> dict[str, Any]:
    for block in _JSON_LD_RE.findall(html or ""):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    return item
    return {}


def _parse_rows(html: str) -> list[Parsed1001Entry]:
    entries = _parse_rows_structured(html)
    if entries:
        _apply_end_seconds(entries)
        return entries
    entries = _parse_rows_fallback(html)
    _apply_end_seconds(entries)
    return entries


def _parse_rows_structured(html: str) -> list[Parsed1001Entry]:
    """Parse tlpItem blocks with separate artist/title/time elements."""
    chunks = re.split(r'<div[^>]*class="[^"]*tlpItem[^"]*"[^>]*>', html or "", flags=re.I)
    entries: list[Parsed1001Entry] = []
    for raw_chunk in chunks[1:]:
        block_html = raw_chunk.rsplit("</div>", 1)[0] if "</div>" in raw_chunk else raw_chunk
        ts_raw = _first_group(_TRACK_TIME_RE.search(block_html))
        if not ts_raw:
            ts_match = re.search(r'data-track-time="(\d{1,2}:\d{2}(?::\d{2})?)"', block_html, re.I)
            ts_raw = ts_match.group(1) if ts_match else ""
        ts, start_s = _parse_timestamp(ts_raw or None)
        artist = _clean_html_text(_first_group(_TRACK_ARTIST_RE.search(block_html)))
        title = _clean_html_text(_first_group(_TRACK_TITLE_RE.search(block_html)))
        if not artist and not title:
            continue
        label = f"{artist} - {title}".strip(" -") if artist and title else (title or artist)
        parsed_artist, parsed_title = split_artist_title(label)
        entries.append(
            Parsed1001Entry(
                position=len(entries) + 1,
                start_seconds=start_s,
                end_seconds=None,
                label=label,
                artist=parsed_artist or artist or None,
                title=parsed_title or title or None,
                timestamp=ts,
                row_id=f"row{len(entries) + 1}",
            )
        )
    return entries


def _parse_rows_fallback(html: str) -> list[Parsed1001Entry]:
    """Fallback for simplified fixture markup."""
    entries: list[Parsed1001Entry] = []
    row_re = re.compile(
        r'data-track-time="(\d{1,2}:\d{2}(?::\d{2})?)"[^>]*data-artist="([^"]*)"[^>]*data-title="([^"]*)"',
        re.IGNORECASE,
    )
    for match in row_re.finditer(html or ""):
        ts, start_s = _parse_timestamp(match.group(1))
        artist = match.group(2).strip() or None
        title = match.group(3).strip() or None
        label = f"{artist} - {title}".strip(" -") if artist and title else (title or artist or "")
        entries.append(
            Parsed1001Entry(
                position=len(entries) + 1,
                start_seconds=start_s,
                end_seconds=None,
                label=label,
                artist=artist,
                title=title,
                timestamp=ts,
                row_id=f"row{len(entries)}",
            )
        )
    _apply_end_seconds(entries)
    return entries


def _apply_end_seconds(entries: list[Parsed1001Entry]) -> None:
    for i, entry in enumerate(entries):
        if i + 1 < len(entries) and entries[i + 1].start_seconds is not None:
            entry.end_seconds = entries[i + 1].start_seconds


def _first_group(match: re.Match[str] | None) -> str:
    return match.group(1).strip() if match else ""


def parse_1001tracklists_html(url: str, html: str) -> Parsed1001Set | None:
    tracklist_id = extract_tracklist_id(url)
    if not tracklist_id:
        return None

    entries = _parse_rows(html)
    if not entries:
        return None

    linked = _extract_linked_urls(html)
    attrs = _parse_json_ld(html)
    title = _parse_title(html)
    return Parsed1001Set(
        tracklist_id=tracklist_id,
        title=title,
        container_url=url.split("?")[0],
        entries=entries,
        linked_urls=linked,
        attrs={"json_ld": attrs} if attrs else {},
    )


def canonical_1001_url(tracklist_id: str, slug: str = "set") -> str:
    return f"https://www.1001tracklists.com/tracklist/{tracklist_id}/{slug}.html"
