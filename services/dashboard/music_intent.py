"""Natural-language detection for dashboard music queue requests."""

from __future__ import annotations

import re

_QUEUE_SUFFIX = re.compile(
    r"\s*(?:in the channel|on discord|please|for me|with your tool)[.!?,]*$",
    re.I,
)

_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"^add\s+(.+?)\s+to\s+(?:the\s+)?(?:queue|playlist)\s*$", re.I), 1),
    (re.compile(r"^add\s+(.+?)\s+to\s+queue\s*$", re.I), 1),
    (re.compile(r"^put\s+(.+?)\s+(?:on|in)\s+(?:the\s+)?(?:queue|playlist)\s*$", re.I), 1),
    (re.compile(r"^play\s+(.+?)\s+next\s*$", re.I), 1),
    (re.compile(r"^queue\s+next\s*:?\s*(.+?)\s*$", re.I), 1),
    (re.compile(r"^queue\s+up\s+(.+?)\s*$", re.I), 1),
    (re.compile(r"^queue\s+(.+?)\s*$", re.I), 1),
]

_PREFIXES = (
    "add to queue ",
    "queue up ",
    "queue song ",
    "queue ",
)


def extract_dashboard_queue_query(text: str) -> str | None:
    """Return the search/URL for a dashboard queue-add request, or None."""
    original = (text or "").strip()
    if not original:
        return None
    tl = original.lower()

    for pat, group in _PATTERNS:
        m = pat.match(original)
        if not m:
            continue
        query = m.group(group).strip(" .,!?'\"")
        query = _QUEUE_SUFFIX.sub("", query).strip(" .,!?'\"")
        if len(query) >= 2:
            return query

    for prefix in _PREFIXES:
        if prefix in tl:
            idx = tl.index(prefix)
            query = original[idx + len(prefix) :].strip()
            query = _QUEUE_SUFFIX.sub("", query).strip(" .,!?'\"")
            if len(query) >= 2:
                return query

    return None


def queue_after_current(text: str) -> bool:
    """True when the user wants the track up next (after current), not at queue tail."""
    raw = (text or "").strip()
    if re.match(r"^play\s+.+\s+next\s*$", raw, re.I):
        return True
    if re.match(r"^queue\s+next\b", raw, re.I):
        return True
    return bool(re.search(r"\bnext\b", raw, re.I)) and "next song" not in raw.lower()


def looks_like_dashboard_queue_request(text: str) -> bool:
    return extract_dashboard_queue_query(text) is not None
