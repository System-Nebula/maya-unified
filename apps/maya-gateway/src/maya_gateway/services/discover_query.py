"""Natural-language query parsing for the discover feed."""

from __future__ import annotations

import re
from dataclasses import dataclass

_WEEK_RE = re.compile(r"\b(this\s+week|past\s+week|last\s+7\s+days?)\b", re.I)
_MONTH_RE = re.compile(r"\b(this\s+month|past\s+month|last\s+30\s+days?)\b", re.I)
_ARTIST_RE = re.compile(
    r"\b(?:for|from|about)\s+([a-z0-9][a-z0-9\s\-']+?)(?:\s*$|\s+(?:this|in|on))",
    re.I,
)
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class ParsedDiscoverQuery:
    window: str
    artist_slug: str | None
    raw: str


def parse_discover_query(raw: str, default_window: str = "7d") -> ParsedDiscoverQuery:
    text = raw.strip()
    window = default_window
    if _WEEK_RE.search(text):
        window = "7d"
    elif _MONTH_RE.search(text):
        window = "30d"

    artist_slug: str | None = None
    match = _ARTIST_RE.search(text)
    if match:
        slug = match.group(1).strip().lower().replace(" ", "-")
        slug = re.sub(r"[^a-z0-9\-]", "", slug)
        if slug:
            artist_slug = slug
    else:
        tokens = [
            t
            for t in re.split(r"\s+", text.lower())
            if t
            and t
            not in {
                "what",
                "whats",
                "what's",
                "new",
                "this",
                "week",
                "month",
                "for",
                "from",
                "about",
                "show",
                "me",
            }
        ]
        if len(tokens) == 1 and _SLUG_RE.match(tokens[0]):
            artist_slug = tokens[0]

    return ParsedDiscoverQuery(window=window, artist_slug=artist_slug, raw=text)
