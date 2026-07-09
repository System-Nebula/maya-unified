"""Shared play/queue query normalization for cmd executors and dashboard resolve."""

from __future__ import annotations

import re

_URL_IN_TEXT_RE = re.compile(r"https?://\S+", re.I)


def normalize_play_query(query: str) -> str:
    """Strip repeated ``/play`` or ``play`` prefixes users sometimes paste twice."""
    q = (query or "").strip()
    while q:
        low = q.lower()
        if low.startswith("/play "):
            q = q[6:].strip()
            continue
        if low == "/play":
            return ""
        if low.startswith("/queue "):
            q = q[7:].strip()
            continue
        if low == "/queue":
            return ""
        if low.startswith("play "):
            q = q[5:].strip()
            continue
        if low.startswith("queue "):
            q = q[6:].strip()
            continue
        break
    return q


def looks_like_cmd_residue(query: str) -> bool:
    """True when the string still looks like a slash-command, not a URL or search."""
    q = (query or "").strip().lower()
    if not q:
        return False
    return (
        q.startswith("/play")
        or q.startswith("/queue")
        or q.startswith("/p ")
        or q == "/p"
    )


def salvage_media_url(query: str) -> str | None:
    """Extract the first http(s) URL embedded in pasted command garbage."""
    match = _URL_IN_TEXT_RE.search(query or "")
    if not match:
        return None
    return normalize_play_query(match.group(0))


def extract_play_query_from_raw_text(raw_text: str) -> str:
    """Derive play query from full ``/play ...`` message text."""
    return extract_cmd_query_from_raw_text(raw_text, cmd="play")


def extract_cmd_query_from_raw_text(raw_text: str, *, cmd: str = "play") -> str:
    """Derive trailing query from a slash-command message."""
    raw = (raw_text or "").strip()
    body = raw[1:].strip() if raw.startswith("/") else raw
    parts = body.split(None, 1)
    head = parts[0].lower() if parts else ""
    query = parts[1].strip() if len(parts) > 1 else ""
    if head == cmd.lower():
        return normalize_play_query(query)
    return normalize_play_query(query if query else body)
