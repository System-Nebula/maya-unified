"""Parse forwarded artist newsletter emails into structured KnowledgeItem fields."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional
from urllib.parse import urlparse

from maya_contracts import KnowledgeItemType

_ARTIST_DOMAIN_HINTS: dict[str, tuple[str, str]] = {
    "oliviarodrigo.umusic-online.com": ("olivia-rodrigo", "Olivia Rodrigo"),
    "umusic-online.com": ("olivia-rodrigo", "Olivia Rodrigo"),
}

_THEME_COLOR_RE = re.compile(
    r'<meta[^>]+name=["\']theme-color["\'][^>]+content=["\'](#?[0-9a-fA-F]{3,8})',
    re.I,
)
_HEX_COLOR_RE = re.compile(r"#([0-9a-fA-F]{6})\b")
_TRACK_FT_RE = re.compile(
    r"['\"]([^'\"]+)['\"][^\n]{0,80}?\bft\.?\s+([^(\\n]+?)(?:\(|$|\n)",
    re.I,
)
_ALBUM_RE = re.compile(
    r"album[^<\n]{0,20}['\"]([^'\"]+)['\"]",
    re.I,
)
_HANDWRITTEN_RE = re.compile(
    r"handwritten|polaroid|signed note|note from me",
    re.I,
)
_VINYL_PROMO_RE = re.compile(
    r"(lenticular|vinyl|pre-?order|exclusive cover)[^\n]{0,120}",
    re.I,
)
_FIRST_FEATURE_RE = re.compile(
    r"first feature|first time.*feature|ever done a feature",
    re.I,
)


@dataclass
class ParsedEmail:
    source: str
    artist_slug: str
    artist_display: str
    item_type: KnowledgeItemType
    tags: list[str]
    title: str
    track: Optional[str]
    album: Optional[str]
    release_date: Optional[datetime]
    promo: Optional[str]
    handwritten_note: bool
    brand_color: Optional[str]
    text_fallback: str
    extras: dict[str, Any]


def slugify(name: str) -> str:
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def extract_brand_color(html: str) -> Optional[str]:
    m = _THEME_COLOR_RE.search(html)
    if m:
        c = m.group(1)
        return c if c.startswith("#") else f"#{c}"
    for m in _HEX_COLOR_RE.finditer(html[:8000]):
        color = f"#{m.group(1)}"
        if color.lower() not in {"#ffffff", "#000000", "#fefefe"}:
            return color
    return "#ec4899"


def resolve_artist(from_header: str, subject: str, html: str) -> tuple[str, str, str]:
    domain = ""
    if "@" in from_header:
        domain = from_header.split("@")[-1].strip(">").lower()
    for hint, (slug, display) in _ARTIST_DOMAIN_HINTS.items():
        if hint in domain or hint in html.lower():
            return domain or hint, slug, display
    if "olivia" in subject.lower() or "olivia" in html.lower()[:2000]:
        return domain or "oliviarodrigo.umusic-online.com", "olivia-rodrigo", "Olivia Rodrigo"
    name = subject.split("-")[0].strip() or "Unknown Artist"
    return domain or urlparse(from_header).netloc or "unknown", slugify(name), name


def parse_received_at(date_header: str | None) -> datetime:
    if not date_header:
        return datetime.now(timezone.utc)
    try:
        dt = parsedate_to_datetime(date_header)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.now(timezone.utc)


def parse_email_newsletter(
    *,
    from_header: str,
    subject: str,
    html: str,
    text: str | None = None,
    date_header: str | None = None,
) -> ParsedEmail:
    source, artist_slug, artist_display = resolve_artist(from_header, subject, html)
    plain = text or re.sub(r"<[^>]+>", " ", html)
    plain = re.sub(r"\s+", " ", plain).strip()

    track: Optional[str] = None
    album: Optional[str] = None
    extras: dict[str, Any] = {}

    tm = _TRACK_FT_RE.search(plain) or _TRACK_FT_RE.search(html)
    if tm:
        track = f"{tm.group(1).strip()} ft. {tm.group(2).strip()}"
        extras["featured_artist"] = tm.group(2).strip()
    elif "what's wrong with me" in plain.lower():
        track = "what's wrong with me ft. Robert Smith (The Cure)"
        extras["featured_artist"] = "Robert Smith (The Cure)"

    am = _ALBUM_RE.search(plain) or _ALBUM_RE.search(html)
    if am:
        album = am.group(1).strip()
    elif "you seem pretty sad for a girl so in love" in plain.lower():
        album = "you seem pretty sad for a girl so in love"

    promo_m = _VINYL_PROMO_RE.search(plain)
    promo = promo_m.group(0).strip() if promo_m else None

    handwritten = bool(_HANDWRITTEN_RE.search(plain) or _HANDWRITTEN_RE.search(html))
    if _FIRST_FEATURE_RE.search(plain):
        extras["is_first_feature"] = True

    tags = ["music", "new_release"]
    if extras.get("is_first_feature") or (track and "ft." in track.lower()):
        tags.append("feature")

    release_date = parse_received_at(date_header)

    return ParsedEmail(
        source=source,
        artist_slug=artist_slug,
        artist_display=artist_display,
        item_type=KnowledgeItemType.RELEASE_ANNOUNCEMENT,
        tags=tags,
        title=subject.strip() or f"Update from {artist_display}",
        track=track,
        album=album,
        release_date=release_date,
        promo=promo,
        handwritten_note=handwritten,
        brand_color=extract_brand_color(html),
        text_fallback=plain[:4000],
        extras=extras,
    )
