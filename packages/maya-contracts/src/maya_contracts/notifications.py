"""User-facing notification contracts.

A persistent, read/unread inbox surfaced in the homepage waybar. Distinct
from the homepage's ephemeral Toast system (which auto-dismisses).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from maya_contracts.common import StrictModel


class NotificationKind(str, Enum):
    NEW_VIDEO = "new_video"
    PERSON_RESOLVED = "person_resolved"
    RELEASE_ANALYZED = "release_analyzed"
    INTEL_EXTRACTED = "intel_extracted"
    ARTIST_RELEASE = "artist_release"
    ARTIST_NEWSLETTER = "artist_newsletter"
    EVENT_ANNOUNCED = "event_announced"
    WANTLIST_MATCH = "wantlist_match"
    SYSTEM = "system"


class Notification(StrictModel):
    id: str
    operator_id: str = "local"
    kind: NotificationKind
    channel_id: Optional[str] = None
    video_id: Optional[str] = None
    title: str
    body: Optional[str] = None
    link: Optional[str] = None
    read: bool = False
    created_at: datetime


class MarkReadRequest(StrictModel):
    ids: list[str]
