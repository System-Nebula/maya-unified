"""Apple Music DJ mix document parser."""

from __future__ import annotations

from typing import Any

from maya_feeds.apple_music import parse_apple_music_html
from maya_feeds.tracklist.filter import classify_tracklist_url
from maya_feeds.tracklist.protocol import TracklistPlatform


class AppleMusicTracklistParser:
    platform = TracklistPlatform.APPLE_MUSIC

    def matches_url(self, url: str) -> bool:
        return classify_tracklist_url(url) == TracklistPlatform.APPLE_MUSIC

    def parse(self, url: str, document: Any):
        if not isinstance(document, str):
            return None
        return parse_apple_music_html(url, document)
