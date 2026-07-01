"""Operator-facing 'follow graph' contracts.

These schemas back the Following management panel: the operator's view of
which Persons (and their per-platform Channels) they're observing, with
per-channel mute/cadence/notify overrides on top of a Person-level default.

Separation from `maya_contracts.feeds`:
- `feeds` models platform-level entities (Channel, Video, Comment) plus the
  ingest-side Subscription (one row per channel, used by the FeedPoller).
- `follow` models the *operator's* relationship to those entities. A single
  channel can be followed by N operators; each operator can carry their own
  mute/cadence overrides. Follows can target either a Person (inherits to
  all attached channels) or a specific Channel (overrides Person-level).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from maya_contracts.common import StrictModel
from maya_contracts.feeds import (
    Channel,
    FetchCadence,
    MatchSignal,
    Platform,
)

PersonKind = Literal["REAL", "FICTIONAL"]
SubscriptionSubjectType = Literal["PERSON", "CHANNEL"]
EffectiveSource = Literal["PERSON", "CHANNEL", "NONE"]


class PersonRef(StrictModel):
    """A Person node enriched with operator-management fields.

    `slug` is the URL-safe handle the operator types into the Following
    panel ("misskatie"); display_name is the friendly label ("MissKatie").
    `kind` lets the operator separate real creators from fictional /
    persona characters when scanning a long follow list.
    """

    id: UUID
    slug: str
    display_name: str
    kind: PersonKind = "REAL"
    realm: Optional[str] = None
    summary: Optional[str] = None
    identity_confidence: float = 0.0
    channels: list[Channel] = []
    created_at: datetime
    updated_at: datetime


class FollowRef(StrictModel):
    """A single follow row owned by an operator.

    Polymorphic subject: either a Person (inherits to all attached channels)
    or a Channel (per-platform override on top of any Person-level row).
    """

    id: UUID
    operator_id: str
    subject_type: SubscriptionSubjectType
    subject_id: UUID
    cadence: FetchCadence = FetchCadence.WEEKLY
    notify_homepage: bool = True
    notify_discord: bool = True
    mpv_autolaunch: bool = False
    muted: bool = False
    last_notified_at: Optional[datetime] = None
    created_at: datetime


class EffectiveFollow(StrictModel):
    """The resolved follow state for a specific channel.

    Computed by overlaying any channel-level FollowRef on top of the
    person-level FollowRef. `source` tells the UI which row decided each
    field so the kebab menu can show "Override at channel" vs
    "Inherits from person".
    """

    channel_id: UUID
    tracking: bool
    source: EffectiveSource
    cadence: FetchCadence = FetchCadence.WEEKLY
    notify_homepage: bool = True
    notify_discord: bool = True
    mpv_autolaunch: bool = False
    muted: bool = False


class FollowTreeChannel(StrictModel):
    channel: Channel
    follow: Optional[FollowRef] = None
    effective: EffectiveFollow


class FollowTreeNode(StrictModel):
    person: PersonRef
    person_follow: Optional[FollowRef] = None
    channels: list[FollowTreeChannel] = []


class FollowTreeResponse(StrictModel):
    operator_id: str
    nodes: list[FollowTreeNode] = []


class CreatePersonRequest(StrictModel):
    slug: str
    display_name: str
    kind: PersonKind = "REAL"
    realm: Optional[str] = None
    summary: Optional[str] = None


class UpdatePersonRequest(StrictModel):
    display_name: Optional[str] = None
    kind: Optional[PersonKind] = None
    realm: Optional[str] = None
    summary: Optional[str] = None


class ResolveChannelRequest(StrictModel):
    """Parse a free-text handle / URL / platform id into a ChannelRef preview.

    v1 only does pure parsing (no live network fetch) so the modal preview
    is instant and offline-friendly. The matcher slot for
    `cross_platform_candidates` is wired but always empty for now — when
    the enrichment worker ships, it fills these in without contract churn.
    """

    input: str
    hint_platform: Optional[Platform] = None


class ResolvedChannelPreview(StrictModel):
    """Locally-derivable shape of a channel before any platform fetch."""

    platform: Platform
    platform_id: str
    handle: str
    display_name: str
    feed_url: Optional[str] = None


class CrossPlatformCandidate(StrictModel):
    channel: ResolvedChannelPreview
    signals: list[MatchSignal] = []


class ResolveChannelResponse(StrictModel):
    channel: ResolvedChannelPreview
    suggested_person_id: Optional[UUID] = None
    cross_platform_candidates: list[CrossPlatformCandidate] = []


class AttachChannelRequest(StrictModel):
    """Attach a channel to a person via the feed_person_channels junction.

    Pass `channel_id` to link an already-resolved channel, or `resolve`
    to do a single-shot parse-and-link. `confidence` defaults to 1.0 since
    the operator is asserting the link manually.
    """

    channel_id: Optional[UUID] = None
    resolve: Optional[ResolveChannelRequest] = None
    confidence: float = 1.0
    signals: list[MatchSignal] = []


class FollowRequest(StrictModel):
    subject_type: SubscriptionSubjectType
    subject_id: UUID
    cadence: FetchCadence = FetchCadence.WEEKLY
    notify_homepage: bool = True
    notify_discord: bool = True
    mpv_autolaunch: bool = False
    muted: bool = False


class UpdateFollowRequest(StrictModel):
    cadence: Optional[FetchCadence] = None
    notify_homepage: Optional[bool] = None
    notify_discord: Optional[bool] = None
    mpv_autolaunch: Optional[bool] = None
    muted: Optional[bool] = None
