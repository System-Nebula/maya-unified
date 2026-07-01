"""Knowledge capture contracts — email newsletters and structured artist updates."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from maya_contracts.common import StrictModel


class KnowledgeItemType(str, Enum):
    RELEASE_ANNOUNCEMENT = "release_announcement"
    NEWSLETTER = "newsletter"
    EDITORIAL = "editorial"


class KnowledgeItem(StrictModel):
    id: str
    source: str
    source_kind: str = "email_newsletter"
    artist_slug: str
    artist_display: str
    type: KnowledgeItemType
    tags: list[str] = []
    title: str
    track: Optional[str] = None
    album: Optional[str] = None
    release_date: Optional[datetime] = None
    promo: Optional[str] = None
    handwritten_note: bool = False
    html_artifact_key: str
    html_artifact_url: str
    text_fallback: Optional[str] = None
    ontology_artist_id: Optional[str] = None
    brand_color: Optional[str] = None
    received_at: datetime
    extras: dict[str, Any] = {}


class InboxArtistSummary(StrictModel):
    artist_slug: str
    artist_display: str
    count: int
    brand_color: Optional[str] = None
    latest_title: Optional[str] = None


class InboxSummaryResponse(StrictModel):
    total: int
    artists: list[InboxArtistSummary]
