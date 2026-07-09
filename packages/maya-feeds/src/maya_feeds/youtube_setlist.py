"""Parse DJ mix tracklists from YouTube video descriptions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from maya_feeds.youtube_intel import timestamp_to_seconds

TRACKLIST_HEADER_RE = re.compile(r"^\s*tracklist\s*:?\s*$", re.IGNORECASE | re.MULTILINE)
TRACKLINE_RE = re.compile(
    r"^\s*(\d{1,2}:\d{2}(?::\d{2})?)\s+(.+?)\s*$",
    re.MULTILINE,
)
COMMENT_TRACKLINE_RE = re.compile(
    r"^\s*(\d{1,2}:\d{2}(?::\d{2})?)\s+(.+?)\s*$",
)
_NARRATIVE_HINT_RE = re.compile(
    r"^(?:I remember|Oh Jesus|To everyone|It was mad|Shoutout)",
    re.IGNORECASE,
)
_SPLIT_RE = re.compile(r"\s+[-–—]\s+|\s+x\s+", re.IGNORECASE)
_YT_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|embed/)|youtu\.be/)([A-Za-z0-9_-]{6,})"
)


@dataclass
class ParsedSetEntry:
    position: int
    start_seconds: int
    end_seconds: int | None
    label: str
    artist: str | None
    title: str | None
    timestamp: str
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedYouTubeSet:
    video_id: str
    title: str
    container_url: str
    duration_seconds: int | None
    entries: list[ParsedSetEntry]
    linked_urls: list[str] = field(default_factory=list)


def extract_youtube_video_id(url: str) -> str | None:
    match = _YT_ID_RE.search(url or "")
    return match.group(1) if match else None


def split_artist_title(label: str) -> tuple[str | None, str | None]:
    text = (label or "").strip()
    if not text:
        return None, None
    parts = _SPLIT_RE.split(text, maxsplit=1)
    if len(parts) == 2:
        artist, title = parts[0].strip(), parts[1].strip()
        return artist or None, title or None
    return None, text


def _tracklist_section(description: str) -> str:
    text = description or ""
    header = TRACKLIST_HEADER_RE.search(text)
    if header:
        section = text[header.end() :].strip()
        # Stop at the next major section header (URLs block, credits, etc.)
        stop = re.search(r"^\s*(?:links|follow|stream|social|credit)s?\s*:?\s*$", section, re.I | re.M)
        if stop:
            section = section[: stop.start()].strip()
        return section
    return text


def parse_tracklist_lines(
    text: str,
    *,
    duration_seconds: int | None = None,
) -> list[ParsedSetEntry]:
    """Parse timestamped track lines from a description or tracklist section."""
    section = _tracklist_section(text)
    raw_lines: list[tuple[str, str, int]] = []
    for match in TRACKLINE_RE.finditer(section):
        ts = match.group(1)
        label = match.group(2).strip()
        if not label:
            continue
        raw_lines.append((ts, label, timestamp_to_seconds(ts)))

    if not raw_lines:
        return []

    entries: list[ParsedSetEntry] = []
    for i, (ts, label, start_s) in enumerate(raw_lines):
        end_s = raw_lines[i + 1][2] if i + 1 < len(raw_lines) else duration_seconds
        artist, title = split_artist_title(label)
        entries.append(
            ParsedSetEntry(
                position=i + 1,
                start_seconds=start_s,
                end_seconds=end_s,
                label=label,
                artist=artist,
                title=title,
                timestamp=ts,
            )
        )
    return entries


def _is_narrative_label(label: str) -> bool:
    text = (label or "").strip()
    if not text:
        return False
    if text.endswith("✦"):
        return True
    return bool(_NARRATIVE_HINT_RE.match(text))


def parse_youtube_comment_tracklist(
    text: str,
    *,
    duration_seconds: int | None = None,
) -> list[ParsedSetEntry]:
    """Parse creator-comment tracklists: timestamp lines plus prose footnotes/narrative."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return []

    raw: list[tuple[str, str, int, str | None, bool]] = []
    pending_footnote: list[str] = []

    def _flush_footnote() -> str | None:
        nonlocal pending_footnote
        if not pending_footnote:
            return None
        note = " ".join(pending_footnote).strip()
        pending_footnote = []
        return note or None

    for line in lines:
        match = COMMENT_TRACKLINE_RE.match(line)
        if match:
            footnote = _flush_footnote()
            if raw:
                ts_prev, label_prev, start_prev, _, is_note_prev = raw[-1]
                if footnote and not is_note_prev:
                    raw[-1] = (ts_prev, label_prev, start_prev, footnote, is_note_prev)
            ts = match.group(1)
            label = match.group(2).strip()
            is_note = _is_narrative_label(label)
            raw.append((ts, label, timestamp_to_seconds(ts), None, is_note))
            continue

        if raw:
            pending_footnote.append(line)
            continue

        pending_footnote.append(line)

    footnote = _flush_footnote()
    if footnote and raw:
        ts_prev, label_prev, start_prev, existing, is_note_prev = raw[-1]
        if not is_note_prev:
            merged = f"{existing} {footnote}".strip() if existing else footnote
            raw[-1] = (ts_prev, label_prev, start_prev, merged, is_note_prev)
        else:
            raw.append(("", footnote, 0, None, True))

    if not raw:
        return []

    entries: list[ParsedSetEntry] = []
    track_lines = [(ts, label, start_s, foot, is_note) for ts, label, start_s, foot, is_note in raw if label]
    for i, (ts, label, start_s, footnote, is_note) in enumerate(track_lines):
        next_start = track_lines[i + 1][2] if i + 1 < len(track_lines) else duration_seconds
        artist, title = split_artist_title(label)
        attrs: dict[str, Any] = {}
        if footnote:
            attrs["footnote"] = footnote
        if is_note:
            attrs["is_narrative"] = True
        entries.append(
            ParsedSetEntry(
                position=len(entries) + 1,
                start_seconds=start_s,
                end_seconds=next_start,
                label=label,
                artist=artist,
                title=title,
                timestamp=ts or fmt_timestamp(start_s),
                attrs=attrs,
            )
        )
    return entries


def fmt_timestamp(seconds: int) -> str:
    s = max(0, int(seconds))
    h = s // 3600
    m = (s % 3600) // 60
    r = s % 60
    if h > 0:
        return f"{h}:{m:02d}:{r:02d}"
    return f"{m}:{r:02d}"


def parse_youtube_set_from_info(info: dict[str, Any]) -> ParsedYouTubeSet | None:
    """Build a parsed set from a yt-dlp extract_info dict."""
    video_id = str(info.get("id") or "").strip()
    if not video_id:
        url = str(info.get("webpage_url") or info.get("original_url") or "")
        video_id = extract_youtube_video_id(url) or ""
    if not video_id:
        return None

    duration = _coerce_duration(info.get("duration"))
    description = str(info.get("description") or "")
    entries = parse_tracklist_lines(description, duration_seconds=duration)
    if not entries:
        comment_text = str(info.get("comment_tracklist") or "")
        if comment_text:
            entries = parse_youtube_comment_tracklist(comment_text, duration_seconds=duration)
    if not entries:
        return None

    container_url = str(
        info.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}"
    )
    linked_urls = _extract_external_urls(description)
    return ParsedYouTubeSet(
        video_id=video_id,
        title=str(info.get("title") or video_id),
        container_url=container_url,
        duration_seconds=duration,
        entries=entries,
        linked_urls=linked_urls,
    )


def _coerce_duration(value: Any) -> int | None:
    if value is None:
        return None
    try:
        sec = int(float(value))
    except (TypeError, ValueError):
        return None
    return sec if sec > 0 else None


def _extract_external_urls(description: str) -> list[str]:
    from maya_feeds.youtube_intel import URL_RE, normalize_url

    out: list[str] = []
    seen: set[str] = set()
    for raw in URL_RE.findall(description or ""):
        if "youtu.be/" in raw or "youtube.com/watch" in raw:
            continue
        canonical = normalize_url(raw)
        if canonical not in seen:
            seen.add(canonical)
            out.append(canonical)
    return out
