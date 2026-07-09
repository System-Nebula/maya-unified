"""Tracklist document parsers — YouTube, 1001tracklists, Apple Music."""

from maya_feeds.tracklist.filter import classify_tracklist_url, is_tracklist_url
from maya_feeds.tracklist.normalize import parsed_to_tracklist_resolved
from maya_feeds.tracklist.protocol import (
    PLATFORM_1001TL,
    PLATFORM_APPLE,
    PLATFORM_YOUTUBE,
    TracklistEntry,
    TracklistPlatform,
    TracklistResolved,
)
from maya_feeds.tracklist.registry import get_tracklist_parser, list_tracklist_platforms

__all__ = [
    "PLATFORM_1001TL",
    "PLATFORM_APPLE",
    "PLATFORM_YOUTUBE",
    "TracklistEntry",
    "TracklistPlatform",
    "TracklistResolved",
    "classify_tracklist_url",
    "get_tracklist_parser",
    "is_tracklist_url",
    "list_tracklist_platforms",
    "parsed_to_tracklist_resolved",
]
