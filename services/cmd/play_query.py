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


_WAKE_PREFIX = re.compile(
    r"^(?:(?:hey|hi|hello|ok|okay|yo)\s+)?(?:@)?maya\b[\s,;:\-]*",
    re.I,
)
_PLAY_UTTERANCE = re.compile(
    r"^(?:please\s+)?(?:can you\s+|could you\s+)?play(?:\s+me)?\s+(.+)$",
    re.I,
)
_PLAY_TRAILING = re.compile(
    r"\s*(?:in the channel|on discord|please|for me|now|with your tool)[.!?,]*$",
    re.I,
)
_PLAYBACK_CONTROL_QUERIES = frozenset(
    {
        "next",
        "skip",
        "pause",
        "stop",
        "resume",
        "previous",
        "it",
        "that",
        "this",
        "something",
        "next song",
        "next track",
        "the next song",
        "the next track",
        "the song",
        "the music",
    }
)


def extract_maya_play_query(text: str) -> str | None:
    """Return search text from ``maya play <query>`` chat/voice utterances.

    Slash ``/play`` stays on the cmd parser. Bare ``play …`` without the wake
    word is left to voice/Discord extractors so game talk is not stolen.
    """
    original = (text or "").strip()
    if not original or original.lstrip().startswith("/"):
        return None
    try:
        from services.game.intent import is_game_play_request

        if is_game_play_request(original):
            return None
    except ImportError:
        pass
    try:
        from services.imagine.intent import classify_music_playback_command

        if classify_music_playback_command(original):
            return None
    except ImportError:
        pass

    wake = _WAKE_PREFIX.match(original)
    if not wake:
        return None
    rest = original[wake.end() :].strip()
    match = _PLAY_UTTERANCE.match(rest)
    if not match:
        return None
    query = match.group(1).strip(" .,!?'\"")
    query = _PLAY_TRAILING.sub("", query).strip(" .,!?'\"")
    if len(query) < 2:
        return None
    if query.lower() in _PLAYBACK_CONTROL_QUERIES:
        return None
    return query


def rewrite_maya_play_as_cmd(text: str) -> str | None:
    """Rewrite ``maya play <query>`` to ``/play <query>``, else None."""
    query = extract_maya_play_query(text)
    if not query:
        return None
    return f"/play {query}"


def looks_like_maya_play_request(text: str) -> bool:
    return extract_maya_play_query(text) is not None
