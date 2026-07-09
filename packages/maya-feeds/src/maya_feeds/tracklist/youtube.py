"""YouTube tracklist document parser."""

from __future__ import annotations

from typing import Any

from maya_feeds.tracklist.filter import classify_tracklist_url
from maya_feeds.tracklist.protocol import TracklistPlatform
from maya_feeds.youtube_setlist import parse_youtube_set_from_info


class YouTubeTracklistParser:
    platform = TracklistPlatform.YOUTUBE

    def matches_url(self, url: str) -> bool:
        return classify_tracklist_url(url) == TracklistPlatform.YOUTUBE

    def parse(self, url: str, document: Any):
        if isinstance(document, dict):
            return parse_youtube_set_from_info(document)
        if isinstance(document, str):
            info = {"webpage_url": url, "description": document}
            vid = url.split("v=")[-1].split("&")[0] if "v=" in url else ""
            if vid:
                info["id"] = vid
            return parse_youtube_set_from_info(info)
        return None
