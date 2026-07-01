"""Overlay-logic tests for the follow-graph tree.

The actual SQL is exercised by the Playwright e2e suite against a real
Postgres. These tests cover the pure overlay function ``assemble_tree``
and the per-channel ``compute_effective`` resolver, using lightweight
fakes that mimic the relevant SQLAlchemy model attributes. That keeps the
core overlay logic — the part that decides whether a channel is muted,
inherits, or has its own override — fully unit-testable without spinning
up a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

import pytest
from maya_contracts import FetchCadence

from maya_gateway.services.follow import assemble_tree, compute_effective


# ---------- lightweight fakes that quack like the SQLA models ----------


@dataclass
class FakePerson:
    id: UUID
    display_name: str
    slug: Optional[str] = None
    kind: str = "REAL"
    realm: Optional[str] = None
    summary: Optional[str] = None
    identity_confidence: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class FakeChannel:
    id: UUID
    platform: str
    platform_id: str
    handle: str
    display_name: str
    description: Optional[str] = None
    subscriber_count: Optional[int] = None
    video_count: Optional[int] = None
    view_count: Optional[int] = None
    joined_at: Optional[datetime] = None
    feed_url: Optional[str] = None
    cadence: str = "weekly"
    last_fetched_at: Optional[datetime] = None
    identity_confidence: float = 0.0


@dataclass
class FakeFollow:
    id: UUID
    operator_id: str
    subject_type: str
    subject_id: UUID
    cadence: str = "weekly"
    notify_homepage: bool = True
    notify_discord: bool = True
    mpv_autolaunch: bool = False
    muted: bool = False
    last_notified_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------- compute_effective ----------


def test_effective_falls_back_to_not_tracking() -> None:
    """No person-level and no channel-level follow → operator isn't tracking."""

    ch_id = uuid4()
    eff = compute_effective(ch_id, None, None)
    assert eff.tracking is False
    assert eff.source == "NONE"
    assert eff.muted is False


def test_effective_inherits_from_person_when_no_channel_override() -> None:
    """A PERSON-level follow propagates its cadence/notify prefs to every
    attached channel and marks ``source=PERSON`` so the UI can show the
    inheritance arrow."""

    ch_id = uuid4()
    person_follow = FakeFollow(
        id=uuid4(),
        operator_id="op",
        subject_type="PERSON",
        subject_id=uuid4(),
        cadence="hourly",
        notify_homepage=True,
        notify_discord=False,
    )
    eff = compute_effective(ch_id, person_follow, None)
    assert eff.tracking is True
    assert eff.source == "PERSON"
    assert eff.cadence is FetchCadence.HOURLY
    assert eff.notify_discord is False


def test_effective_channel_override_wins_over_person() -> None:
    """A CHANNEL row beats the PERSON row for every field it sets — that's
    the whole point of per-channel overrides (mute one platform without
    losing the follow on the others)."""

    ch_id = uuid4()
    person_follow = FakeFollow(
        id=uuid4(),
        operator_id="op",
        subject_type="PERSON",
        subject_id=uuid4(),
        cadence="weekly",
        notify_homepage=True,
        notify_discord=True,
    )
    channel_follow = FakeFollow(
        id=uuid4(),
        operator_id="op",
        subject_type="CHANNEL",
        subject_id=ch_id,
        cadence="daily",
        muted=True,
        notify_discord=False,
    )
    eff = compute_effective(ch_id, person_follow, channel_follow)
    assert eff.source == "CHANNEL"
    assert eff.muted is True
    assert eff.tracking is False  # muted ⇒ not tracking
    assert eff.cadence is FetchCadence.DAILY
    assert eff.notify_discord is False


def test_effective_channel_override_without_person_follow() -> None:
    """Following a single channel without an umbrella person follow is a
    legitimate state (e.g. operator only cares about the YT channel of a
    creator whose IG they don't want)."""

    ch_id = uuid4()
    channel_follow = FakeFollow(
        id=uuid4(),
        operator_id="op",
        subject_type="CHANNEL",
        subject_id=ch_id,
    )
    eff = compute_effective(ch_id, None, channel_follow)
    assert eff.source == "CHANNEL"
    assert eff.tracking is True


# ---------- assemble_tree ----------


def test_assemble_tree_misskatie_3_channels_with_ig_muted() -> None:
    """End-to-end overlay scenario from the spec:

    - Person ``misskatie`` is followed at the PERSON level.
    - Three channels attached: YT, Instagram, TikTok.
    - One CHANNEL-level override mutes Instagram.

    Expected effective state: YT + TikTok inherit (tracking), Instagram is
    muted (not tracking, source=CHANNEL).
    """

    person_id = uuid4()
    yt_id = uuid4()
    ig_id = uuid4()
    tt_id = uuid4()

    person = FakePerson(
        id=person_id,
        slug="misskatie",
        display_name="MissKatie",
        kind="REAL",
    )
    yt = FakeChannel(
        id=yt_id,
        platform="youtube",
        platform_id="UCFldqmSKhOZQZdfUuPMJjpw",
        handle="@MissKatie",
        display_name="MissKatie",
        cadence="weekly",
    )
    ig = FakeChannel(
        id=ig_id,
        platform="instagram",
        platform_id="heymisskatie",
        handle="@heymisskatie",
        display_name="heymisskatie",
        cadence="weekly",
    )
    tt = FakeChannel(
        id=tt_id,
        platform="tiktok",
        platform_id="heymisskatiee",
        handle="@heymisskatiee",
        display_name="heymisskatiee",
        cadence="weekly",
    )

    person_follow = FakeFollow(
        id=uuid4(),
        operator_id="local",
        subject_type="PERSON",
        subject_id=person_id,
        cadence="weekly",
        notify_homepage=True,
        notify_discord=True,
    )
    ig_override = FakeFollow(
        id=uuid4(),
        operator_id="local",
        subject_type="CHANNEL",
        subject_id=ig_id,
        muted=True,
    )

    tree = assemble_tree(
        operator_id="local",
        persons=[person],
        channels_by_person={person_id: [yt, ig, tt]},
        follows=[person_follow, ig_override],
    )

    assert tree.operator_id == "local"
    assert len(tree.nodes) == 1
    node = tree.nodes[0]
    assert node.person.slug == "misskatie"
    assert node.person_follow is not None
    assert len(node.channels) == 3

    by_platform = {c.channel.platform.value: c for c in node.channels}
    yt_row = by_platform["youtube"]
    ig_row = by_platform["instagram"]
    tt_row = by_platform["tiktok"]

    assert yt_row.effective.tracking is True
    assert yt_row.effective.source == "PERSON"
    assert yt_row.follow is None

    assert ig_row.effective.tracking is False
    assert ig_row.effective.source == "CHANNEL"
    assert ig_row.effective.muted is True
    assert ig_row.follow is not None

    assert tt_row.effective.tracking is True
    assert tt_row.effective.source == "PERSON"


def test_assemble_tree_unfollowed_person_lists_channels_as_not_tracked() -> None:
    """A Person can exist with attached channels but no operator follow —
    that's just a known entity the operator hasn't subscribed to yet."""

    person_id = uuid4()
    yt_id = uuid4()
    person = FakePerson(id=person_id, slug="ghost", display_name="Ghost")
    yt = FakeChannel(
        id=yt_id,
        platform="youtube",
        platform_id="UC00000000000000000000",
        handle="@ghost",
        display_name="ghost",
    )

    tree = assemble_tree(
        operator_id="local",
        persons=[person],
        channels_by_person={person_id: [yt]},
        follows=[],
    )

    node = tree.nodes[0]
    assert node.person_follow is None
    assert len(node.channels) == 1
    assert node.channels[0].effective.tracking is False
    assert node.channels[0].effective.source == "NONE"


def test_assemble_tree_empty_when_no_persons() -> None:
    tree = assemble_tree(
        operator_id="local",
        persons=[],
        channels_by_person={},
        follows=[],
    )
    assert tree.nodes == []


def test_assemble_tree_only_returns_follows_for_subjects_in_scope() -> None:
    """Stray follow rows targeting subjects not in the loaded slice are
    ignored — they belong to other persons/operators and shouldn't bleed
    into this tree. assemble_tree trusts the caller to pre-filter."""

    person_id = uuid4()
    yt_id = uuid4()
    person = FakePerson(id=person_id, display_name="A")
    yt = FakeChannel(
        id=yt_id,
        platform="youtube",
        platform_id="UC11111111111111111111",
        handle="@a",
        display_name="A",
    )

    # Stranger follow doesn't apply: subject_type=PERSON but subject_id is
    # someone else. The function still walks the data, but since our only
    # person isn't followed, the channel stays in the NONE state.
    stranger_follow = FakeFollow(
        id=uuid4(),
        operator_id="local",
        subject_type="PERSON",
        subject_id=uuid4(),
    )
    tree = assemble_tree(
        operator_id="local",
        persons=[person],
        channels_by_person={person_id: [yt]},
        follows=[stranger_follow],
    )
    assert tree.nodes[0].channels[0].effective.source == "NONE"
