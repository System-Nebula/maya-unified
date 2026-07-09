"""Tracklist document protocol — shared types for DJ set parsers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from maya_feeds.apple_music import ParsedAppleSet
from maya_feeds.tracklists_1001 import Parsed1001Set
from maya_feeds.youtube_setlist import ParsedYouTubeSet

PLATFORM_YOUTUBE = "yt"
PLATFORM_1001TL = "1001tl"
PLATFORM_APPLE = "apple_music"

ParsedSetDocument = ParsedYouTubeSet | Parsed1001Set | ParsedAppleSet


class TracklistPlatform(str, Enum):
    YOUTUBE = PLATFORM_YOUTUBE
    TRACKLISTS_1001 = PLATFORM_1001TL
    APPLE_MUSIC = PLATFORM_APPLE


@dataclass
class TracklistSourceRef:
    schema_id: str
    external_id: str
    url: str | None = None
    confidence: float = 1.0


@dataclass
class TracklistEntry:
    position: int
    start_seconds: int
    end_seconds: int | None
    label: str
    artist: str | None
    title: str | None
    source_refs: list[TracklistSourceRef] = field(default_factory=list)
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class TracklistResolved:
    set_key: str
    title: str
    container_url: str
    container_schema: str
    entries: list[TracklistEntry]
    linked_sets: list[TracklistSourceRef] = field(default_factory=list)
    attrs: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class TracklistDocumentParser(Protocol):
    platform: TracklistPlatform

    def matches_url(self, url: str) -> bool: ...

    def parse(self, url: str, document: Any) -> ParsedSetDocument | None: ...
