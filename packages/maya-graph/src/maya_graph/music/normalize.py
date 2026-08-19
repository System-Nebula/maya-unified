"""Normalize messy music strings into artist / title / album primitives.

Share paths, Discogs-style ``Artist (2)`` suffixes, and ``(Radio Edit)`` /
``(Someone Remix)`` tags all collapse onto the same fields the Postgres
graph already stores (CanonicalWork, ArtistRef, fingerprint).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from pathlib import PureWindowsPath

from maya_graph.artist_bridge import slugify
from maya_graph.music.primitives import (
    ArtistRef,
    CanonicalWork,
    canonical_fingerprint,
    work_key_from_fingerprint,
)
from maya_graph.projector import normalize_key

_SKIP_DIRS = {
    "music",
    "downloads",
    "shared",
    "incomplete",
    "users",
    "documents",
    "audio",
    "flac",
    "mp3",
    "lossless",
}
_ARTIST_TITLE_RE = re.compile(r"\s+[-–—:]\s+")
_TRACK_NUM_RE = re.compile(r"^(\d{1,3})\s*[\.\-_]\s*(.+)$")
_DISCOGS_NUM_RE = re.compile(r"\s+\(\d+\)\s*$")
_FEAT_RE = re.compile(
    r"\s*[\(\[]?\s*(?:feat(?:uring)?|ft|with)\.?\s+([^)\]]+)[)\]]?",
    re.IGNORECASE,
)
_REMIX_RE = re.compile(
    r"[\(\[]\s*(.+?)\s+(remix|edit|bootleg|flip|rework|vip)\s*[\)\]]",
    re.IGNORECASE,
)
_VERSION_RE = re.compile(
    r"[\(\[]\s*(live|radio\s*edit|acoustic|instrumental|remaster(?:ed)?"
    r"|mono|stereo|deluxe|extended|club\s*mix|7\s*[\"”']|12\s*[\"”'])\s*[\)\]]",
    re.IGNORECASE,
)
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class ParsedTrack:
    """Best-effort identity extracted from a path, query, or catalog row."""

    artist: str | None = None
    title: str | None = None
    base_title: str | None = None
    album: str | None = None
    remix: str | None = None
    version: str | None = None
    featured: str | None = None
    track_number: int | None = None
    year: int | None = None
    isrc: str | None = None
    mb_recording_id: str | None = None
    mb_artist_id: str | None = None

    def display_title(self) -> str:
        return (self.title or self.base_title or "").strip()

    def fingerprint(self) -> str | None:
        artist = (self.artist or "").strip()
        title = (self.base_title or self.title or "").strip()
        if not artist or not title:
            return None
        return canonical_fingerprint(artist, title, self.remix, self.version)


def clean_name(value: str | None) -> str | None:
    """Strip Discogs numeric suffixes and collapse whitespace."""
    if value is None:
        return None
    text = _WS_RE.sub(" ", value.replace("_", " ").replace("\\u0026", "&")).strip()
    text = _DISCOGS_NUM_RE.sub("", text).strip(" -_./")
    return text or None


def split_artist_title(text: str) -> tuple[str | None, str]:
    """Split ``Artist - Title`` (one cut). Title-only queries return ``(None, text)``."""
    raw = (text or "").strip()
    if not raw:
        return None, ""
    parts = _ARTIST_TITLE_RE.split(raw, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return clean_name(parts[0]), clean_name(parts[1]) or parts[1].strip()
    return None, clean_name(raw) or raw


def split_remix_version(title: str) -> tuple[str, str | None, str | None]:
    """Peel remix/version tags off a title. Returns ``(base, remix, version)``."""
    remix: str | None = None
    version: str | None = None
    rest = title
    remix_match = _REMIX_RE.search(rest)
    if remix_match:
        remix = clean_name(remix_match.group(1))
        rest = (rest[: remix_match.start()] + rest[remix_match.end() :]).strip()
    version_match = _VERSION_RE.search(rest)
    if version_match:
        version = normalize_key(version_match.group(1)) or None
        rest = (rest[: version_match.start()] + rest[version_match.end() :]).strip()
    featured: str | None = None
    feat_match = _FEAT_RE.search(rest)
    if feat_match:
        featured = clean_name(feat_match.group(1))
        rest = (rest[: feat_match.start()] + rest[feat_match.end() :]).strip()
    base = clean_name(rest) or rest
    if featured and not remix:
        # Keep featured as metadata only; identity stays the primary artist + base title.
        pass
    return base, remix, version


def parse_share_path(path: str) -> ParsedTrack:
    """Parse a Soulseek/Windows share path into artist, album, and title.

    Never treats a peer username as the artist — that belongs on the recording.
    """
    if not (path or "").strip():
        return ParsedTrack()
    pw = PureWindowsPath(path.replace("/", "\\"))
    stem = pw.stem
    parent_names = [
        part
        for part in pw.parts[:-1]
        if part not in {"\\", "/"} and ":" not in part
    ]
    meaningful = [name for name in parent_names if name.lower() not in _SKIP_DIRS]

    artist: str | None = None
    album: str | None = None
    if len(meaningful) >= 2:
        artist = clean_name(meaningful[-2])
        album = clean_name(meaningful[-1])
    elif len(meaningful) == 1:
        album = clean_name(meaningful[0])

    track_number: int | None = None
    title = stem
    numbered = _TRACK_NUM_RE.match(stem)
    if numbered:
        track_number = int(numbered.group(1))
        title = numbered.group(2).strip()

    line_artist, line_title = split_artist_title(title)
    if line_artist and not artist:
        artist = line_artist
        title = line_title
    elif line_title:
        title = line_title if line_artist and artist else (clean_name(title) or title)

    featured: str | None = None
    feat_match = _FEAT_RE.search(title)
    if feat_match:
        featured = clean_name(feat_match.group(1))
    base, remix, version = split_remix_version(title)
    return ParsedTrack(
        artist=artist,
        title=clean_name(title) or title,
        base_title=base,
        album=album,
        remix=remix,
        version=version,
        featured=featured,
        track_number=track_number,
    )


def merge_parsed(primary: ParsedTrack, overlay: ParsedTrack) -> ParsedTrack:
    """Fill empty fields on ``primary`` from ``overlay`` (overlay does not overwrite)."""
    updates = {}
    for field_name in (
        "artist",
        "title",
        "base_title",
        "album",
        "remix",
        "version",
        "featured",
        "track_number",
        "year",
        "isrc",
        "mb_recording_id",
        "mb_artist_id",
    ):
        if getattr(primary, field_name) in (None, "") and getattr(overlay, field_name) not in (
            None,
            "",
        ):
            updates[field_name] = getattr(overlay, field_name)
    return replace(primary, **updates) if updates else primary


def parsed_from_query(text: str, *, artist: str | None = None, title: str | None = None) -> ParsedTrack:
    if artist or title:
        display = title or text
        base, remix, version = split_remix_version(display or "")
        return ParsedTrack(
            artist=clean_name(artist),
            title=clean_name(display) or display,
            base_title=base or clean_name(display),
            remix=remix,
            version=version,
        )
    split_artist, split_title = split_artist_title(text)
    base, remix, version = split_remix_version(split_title)
    return ParsedTrack(
        artist=split_artist,
        title=clean_name(split_title) or split_title,
        base_title=base,
        remix=remix,
        version=version,
    )


def artist_refs(*names: str | None) -> tuple[ArtistRef, ...]:
    refs: list[ArtistRef] = []
    seen: set[str] = set()
    for name in names:
        cleaned = clean_name(name)
        if not cleaned:
            continue
        slug = slugify(cleaned)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        refs.append(ArtistRef(slug=slug, name=cleaned))
    return tuple(refs)


def fingerprint_work(parsed: ParsedTrack) -> CanonicalWork | None:
    """Internal ``fp:`` work when catalogs have not assigned an external id yet."""
    artist = parsed.artist
    title = parsed.base_title or parsed.title
    if not artist or not title:
        return None
    fp = canonical_fingerprint(artist, title, parsed.remix, parsed.version)
    return CanonicalWork(
        key=work_key_from_fingerprint(fp),
        label=parsed.display_title() or title,
        aliases=(fp,),
        artists=artist_refs(artist, parsed.featured),
        attrs={
            "album": parsed.album,
            "remix": parsed.remix,
            "version": parsed.version,
            "isrc": parsed.isrc,
            "base_title": title,
        },
    )


def slskd_external_id(username: str, filename: str, size: int | None = None) -> str:
    """Stable recording id that fits ``MusicPlatformLink.external_id`` (255)."""
    raw = f"{username}\n{filename}\n{size or 0}".encode()
    digest = hashlib.sha1(raw).hexdigest()[:16]
    base = PureWindowsPath(filename.replace("/", "\\")).name
    return f"{username}:{digest}:{base}"[:255]
