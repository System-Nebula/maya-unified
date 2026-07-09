"""Tracklist URL filter — classify music DJ-set document hosts."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from maya_feeds.tracklist.protocol import TracklistPlatform
from maya_feeds.youtube_setlist import extract_youtube_video_id

_YT_HOSTS = ("youtube.com", "youtu.be", "www.youtube.com", "m.youtube.com")
_1001_TRACKLIST_RE = re.compile(r"1001tracklists\.com/tracklist/[a-z0-9]+", re.I)
_APPLE_ALBUM_RE = re.compile(r"music\.apple\.com/.+/album/", re.I)


def classify_tracklist_url(url: str) -> TracklistPlatform | None:
    text = (url or "").strip()
    if not text.startswith(("http://", "https://")):
        return None
    host = (urlparse(text).netloc or "").lower().removeprefix("www.")
    if any(h in host for h in _YT_HOSTS) or host == "youtu.be":
        if extract_youtube_video_id(text):
            return TracklistPlatform.YOUTUBE
        qs = parse_qs(urlparse(text).query)
        if qs.get("v", [None])[0]:
            return TracklistPlatform.YOUTUBE
        return None
    if _1001_TRACKLIST_RE.search(text):
        return TracklistPlatform.TRACKLISTS_1001
    if _APPLE_ALBUM_RE.search(text):
        return TracklistPlatform.APPLE_MUSIC
    return None


def is_tracklist_url(url: str) -> bool:
    return classify_tracklist_url(url) is not None
