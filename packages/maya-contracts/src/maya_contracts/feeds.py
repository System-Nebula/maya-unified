"""Creator-intel feed contracts.

Generic, public-safe schemas for the feed-manager pipeline: subscribe to a
creator's platform handle, model Channel/Video/Comment/Person nodes, and
expose cross-platform entity-resolution results.

No creator-specific handles or watch lists live here — those are loaded at
runtime from env/config outside this repo (see docs/public-boundary.md).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from maya_contracts.common import StrictModel
from maya_contracts.intel import AnalysisConfig, AnalysisStatus


class Platform(str, Enum):
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    RSS = "rss"
    GITHUB = "github"


class FetchCadence(str, Enum):
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MANUAL = "manual"


class CommentWindow(str, Enum):
    T24H = "t24h"
    T72H = "t72h"
    T1W = "t1w"
    T1M = "t1m"


class MatchSignalKind(str, Enum):
    HANDLE_SIMILARITY = "handle_similarity"
    BIO_TEXT_MATCH = "bio_text_match"
    PROFILE_LINK_MATCH = "profile_link_match"
    AVATAR_FACE_MATCH = "avatar_face_match"
    EMBEDDING_PROXIMITY = "embedding_proximity"


class MatchSignal(StrictModel):
    kind: MatchSignalKind
    score: float
    detail: Optional[str] = None


class ChannelRef(StrictModel):
    platform: Platform
    platform_id: str
    handle: str


class Channel(StrictModel):
    id: str
    platform: Platform
    platform_id: str
    handle: str
    display_name: str
    description: Optional[str] = None
    subscriber_count: Optional[int] = None
    video_count: Optional[int] = None
    view_count: Optional[int] = None
    joined_at: Optional[datetime] = None
    feed_url: Optional[str] = None
    cadence: FetchCadence = FetchCadence.WEEKLY
    last_fetched_at: Optional[datetime] = None
    identity_confidence: float = 0.0


class TagRef(StrictModel):
    id: str
    canonical_path: str
    confidence: float = 1.0


class Video(StrictModel):
    id: str
    video_id: str
    channel_id: str
    title: str
    description: Optional[str] = None
    published_at: datetime
    updated_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    is_short: bool = False
    thumbnail_url: Optional[str] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    tags: list[TagRef] = []
    has_embedding: bool = False
    has_thumbnail_embedding: bool = False
    analysis_status: Optional[AnalysisStatus] = None


class CommentSnapshot(StrictModel):
    id: str
    video_id: str
    fetched_at: datetime
    fetch_window: CommentWindow
    total_count: int


class Comment(StrictModel):
    id: str
    platform_comment_id: str
    snapshot_id: str
    author_handle: Optional[str] = None
    author_channel_id: Optional[str] = None
    text: str
    like_count: int = 0
    published_at: datetime
    reply_count: int = 0
    is_creator_reply: bool = False
    sentiment_score: Optional[float] = None
    has_embedding: bool = False


class PersonChannelLink(StrictModel):
    person_id: str
    channel_id: str
    confidence: float
    signals: list[MatchSignal] = []


class Person(StrictModel):
    id: str
    display_name: str
    summary: Optional[str] = None
    identity_confidence: float = 0.0
    channels: list[PersonChannelLink] = []


class CrossPlatformMatch(StrictModel):
    platform: Platform
    handle: str
    confidence: float
    signals: list[MatchSignal] = []


class SubscribeRequest(StrictModel):
    platform: Platform
    handle: str
    cadence: FetchCadence = FetchCadence.WEEKLY
    fetch_comments: bool = True
    comment_windows: list[CommentWindow] = [
        CommentWindow.T24H,
        CommentWindow.T72H,
        CommentWindow.T1W,
    ]
    analysis_config: Optional[AnalysisConfig] = None


class SubscribeResponse(StrictModel):
    channel: Channel
    person: Optional[Person] = None
    identity_confidence: float = 0.0
    cross_platform_matches: list[CrossPlatformMatch] = []


class VideoSimilarity(StrictModel):
    video_id: str
    score: float


class MergePersonsRequest(StrictModel):
    source_person_id: str
    target_person_id: str
    note: Optional[str] = None
