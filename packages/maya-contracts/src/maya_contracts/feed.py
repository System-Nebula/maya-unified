"""Feed service request/response contracts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from maya_contracts.common import MediaSourceStatus, StrictModel


class MediaResponse(StrictModel):
    id: UUID
    source_url: str
    storage_key: str | None
    media_type: str
    source_status: MediaSourceStatus
    post_id: UUID | None
    comment_id: UUID | None
    created_at: datetime


class CommentResponse(StrictModel):
    id: UUID
    reddit_id: str
    author: str | None
    body: str
    score: int
    depth: int
    is_submitter: bool
    permalink: str | None
    reddit_created_utc: datetime
    replies: list["CommentResponse"] = []


class PostResponse(StrictModel):
    id: UUID
    reddit_id: str
    source_type: str
    target: str
    title: str
    selftext: str
    url: str
    permalink: str | None
    author: str | None
    score: int
    num_comments: int
    upvote_ratio: float
    over_18: bool
    archive_path: str | None
    archived_at: datetime | None
    reddit_created_utc: datetime
    created_at: datetime
    media: list[MediaResponse] = []


class SourceResponse(StrictModel):
    source_type: str
    name: str
    subscribers: int | None
    description: str | None
    post_count: int
    media_count: int
    is_active: bool
    created_at: datetime


class SearchResult(StrictModel):
    post: PostResponse
    rank: float


class PresignedUrlResponse(StrictModel):
    url: str
    expires_in: int


class SubjectResponse(StrictModel):
    id: UUID
    name: str
    display_name: str | None
