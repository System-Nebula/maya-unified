"""Unified discovery feed contracts — ranked What's New surface."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from maya_contracts.common import PaginatedResponse, StrictModel


class FeedLane(str, Enum):
    FOLLOWED = "followed"
    ALGORITHMIC = "algorithmic"
    LOCAL_EVENT = "local_event"


class FeedItemType(str, Enum):
    NEW_VIDEO = "new_video"
    NEW_RELEASE = "new_release"
    EVENT_ANNOUNCED = "event_announced"
    EDITORIAL = "editorial"
    WANTLIST_MATCH = "wantlist_match"


class FeedItem(StrictModel):
    id: str
    lane: FeedLane
    type: FeedItemType
    source: str
    title: str
    subtitle: Optional[str] = None
    tags: list[str] = []
    artist_ids: list[str] = []
    event_date: Optional[datetime] = None
    score: float
    published_at: datetime
    link: Optional[str] = None
    attrs: dict[str, Any] = {}


class FeedResponse(StrictModel):
    items: list[FeedItem]
    next_cursor: Optional[str] = None
    window: str
    total: int


class OperatorPreferences(StrictModel):
    operator_id: str
    genre_weights: dict[str, float] = {}
    source_enabled: dict[str, bool] = {}
    source_trust: dict[str, float] = {}
    metro: Optional[str] = "minneapolis"
    window_default: str = "7d"


class OperatorPreferencesPatch(StrictModel):
    genre_weights: Optional[dict[str, float]] = None
    source_enabled: Optional[dict[str, bool]] = None
    source_trust: Optional[dict[str, float]] = None
    metro: Optional[str] = None
    window_default: Optional[str] = None


class WantlistMatch(StrictModel):
    release_id: str
    title: str
    artist: str
    url: Optional[str] = None
    listed_at: Optional[datetime] = None


class CollectionSummary(StrictModel):
    operator_id: str
    vinyl_count: int = 0
    digital_count: int = 0
    wantlist_matches: list[WantlistMatch] = []
    synced_at: Optional[datetime] = None


class ArtistActivityState(str, Enum):
    NEW_RELEASE = "new_release"
    EVENT_ANNOUNCED = "event_announced"
    FEATURED = "featured"
    IDLE = "idle"


class ArtistTrackerEntry(StrictModel):
    person_id: Optional[str] = None
    ontology_artist_id: Optional[str] = None
    slug: str
    display_name: str
    activity_state: ArtistActivityState = ArtistActivityState.IDLE
    latest_title: Optional[str] = None
    latest_at: Optional[datetime] = None
    unseen: bool = False


class ArtistTrackerResponse(StrictModel):
    items: list[ArtistTrackerEntry]


class DiscoverEvent(StrictModel):
    id: str
    title: str
    venue: Optional[str] = None
    metro: str
    event_date: datetime
    ticket_status: Optional[str] = None
    link: Optional[str] = None
    source: str = "ra"


class DiscoverEventsResponse(StrictModel):
    items: list[DiscoverEvent]
    metro: str


DEFAULT_SOURCE_ENABLED: dict[str, bool] = {
    "youtube": True,
    "github": True,
    "beatport": True,
    "discogs": True,
    "bandcamp": True,
    "ra": True,
    "redacted": False,
    "email_newsletter": True,
}

DEFAULT_SOURCE_TRUST: dict[str, float] = {
    "youtube": 1.0,
    "github": 0.9,
    "beatport": 0.85,
    "discogs": 0.9,
    "bandcamp": 0.8,
    "ra": 0.75,
    "redacted": 0.7,
    "email_newsletter": 0.95,
}

DEFAULT_GENRE_WEIGHTS: dict[str, float] = {
    "techno": 0.0,
    "house": 0.0,
    "dubstep": 0.0,
    "brostep": 0.0,
    "drum-and-bass": 0.0,
    "ambient": 0.0,
    "lofi": 0.0,
}


FeedPage = PaginatedResponse[FeedItem]
