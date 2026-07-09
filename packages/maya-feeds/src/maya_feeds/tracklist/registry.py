"""Tracklist parser registry."""

from __future__ import annotations

from maya_feeds.tracklist.apple_music import AppleMusicTracklistParser
from maya_feeds.tracklist.filter import classify_tracklist_url
from maya_feeds.tracklist.protocol import TracklistDocumentParser, TracklistPlatform
from maya_feeds.tracklist.tracklists_1001 import Tracklists1001Parser
from maya_feeds.tracklist.youtube import YouTubeTracklistParser

_PARSERS: tuple[TracklistDocumentParser, ...] = (
    YouTubeTracklistParser(),
    Tracklists1001Parser(),
    AppleMusicTracklistParser(),
)

_BY_PLATFORM: dict[TracklistPlatform, TracklistDocumentParser] = {
    p.platform: p for p in _PARSERS
}


def list_tracklist_platforms() -> list[TracklistPlatform]:
    return list(_BY_PLATFORM.keys())


def get_tracklist_parser(url: str) -> TracklistDocumentParser | None:
    platform = classify_tracklist_url(url)
    if platform is None:
        return None
    return _BY_PLATFORM.get(platform)
