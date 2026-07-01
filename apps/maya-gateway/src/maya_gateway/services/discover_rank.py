"""Unified discover feed ranker — merges creator-intel and ontology signals."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from maya_contracts import (
    DEFAULT_GENRE_WEIGHTS,
    DEFAULT_SOURCE_ENABLED,
    DEFAULT_SOURCE_TRUST,
    FeedItem,
    FeedItemType,
    FeedLane,
    FeedResponse,
    InboxArtistSummary,
    InboxSummaryResponse,
    OperatorPreferences,
)
from maya_db import (
    Channel as ChannelDB,
    CollectionSummary as CollectionSummaryDB,
    FeedAnalysis as FeedAnalysisDB,
    Follow as FollowDB,
    KnowledgeItem as KnowledgeItemDB,
    OperatorPreferences as OperatorPreferencesDB,
    Person as PersonDB,
    PersonChannel as PersonChannelDB,
    Video as VideoDB,
)
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

_WINDOW_DAYS = {"7d": 7, "30d": 30}


@dataclass
class _Candidate:
    id: str
    lane: FeedLane
    type: FeedItemType
    source: str
    title: str
    subtitle: str | None
    tags: list[str]
    artist_ids: list[str]
    event_date: datetime | None
    published_at: datetime
    link: str | None
    attrs: dict[str, Any]
    follow_boost: float = 0.0
    community_weight: float = 0.0


def _window_start(window: str) -> datetime:
    days = _WINDOW_DAYS.get(window, 7)
    return datetime.now(timezone.utc) - timedelta(days=days)


def _encode_cursor(published_at: datetime, item_id: str) -> str:
    payload = {"t": published_at.isoformat(), "id": item_id}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str] | None:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return datetime.fromisoformat(payload["t"]), payload["id"]
    except Exception:
        return None


def _default_preferences(operator_id: str) -> OperatorPreferences:
    return OperatorPreferences(
        operator_id=operator_id,
        genre_weights=dict(DEFAULT_GENRE_WEIGHTS),
        source_enabled=dict(DEFAULT_SOURCE_ENABLED),
        source_trust=dict(DEFAULT_SOURCE_TRUST),
        metro="minneapolis",
        window_default="7d",
    )


async def get_or_create_preferences(
    session: AsyncSession, operator_id: str
) -> OperatorPreferences:
    row = (
        await session.execute(
            select(OperatorPreferencesDB).where(
                OperatorPreferencesDB.operator_id == operator_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        defaults = _default_preferences(operator_id)
        row = OperatorPreferencesDB(
            operator_id=operator_id,
            genre_weights=defaults.genre_weights,
            source_enabled=defaults.source_enabled,
            source_trust=defaults.source_trust,
            metro=defaults.metro,
            window_default=defaults.window_default,
        )
        session.add(row)
        await session.flush()
    return OperatorPreferences(
        operator_id=row.operator_id,
        genre_weights=dict(row.genre_weights or {}),
        source_enabled={**DEFAULT_SOURCE_ENABLED, **(row.source_enabled or {})},
        source_trust={**DEFAULT_SOURCE_TRUST, **(row.source_trust or {})},
        metro=row.metro,
        window_default=row.window_default or "7d",
    )


async def patch_preferences(
    session: AsyncSession,
    operator_id: str,
    *,
    genre_weights: dict[str, float] | None = None,
    source_enabled: dict[str, bool] | None = None,
    source_trust: dict[str, float] | None = None,
    metro: str | None = None,
    window_default: str | None = None,
) -> OperatorPreferences:
    current = await get_or_create_preferences(session, operator_id)
    row = (
        await session.execute(
            select(OperatorPreferencesDB).where(
                OperatorPreferencesDB.operator_id == operator_id
            )
        )
    ).scalar_one()
    if genre_weights is not None:
        merged = {**current.genre_weights, **genre_weights}
        row.genre_weights = merged
    if source_enabled is not None:
        merged = {**current.source_enabled, **source_enabled}
        row.source_enabled = merged
    if source_trust is not None:
        merged = {**current.source_trust, **source_trust}
        row.source_trust = merged
    if metro is not None:
        row.metro = metro
    if window_default is not None:
        row.window_default = window_default
    await session.flush()
    return await get_or_create_preferences(session, operator_id)


async def _followed_channel_ids(
    session: AsyncSession, operator_id: str
) -> set[UUID]:
    follows = (
        await session.execute(
            select(FollowDB).where(
                and_(
                    FollowDB.operator_id == operator_id,
                    FollowDB.deleted_at.is_(None),
                    FollowDB.muted.is_(False),
                )
            )
        )
    ).scalars().all()
    channel_ids: set[UUID] = set()
    person_ids: set[UUID] = set()
    for f in follows:
        if f.subject_type == "CHANNEL":
            channel_ids.add(f.subject_id)
        elif f.subject_type == "PERSON":
            person_ids.add(f.subject_id)
    if person_ids:
        links = (
            await session.execute(
                select(PersonChannelDB.channel_id).where(
                    PersonChannelDB.person_id.in_(person_ids)
                )
            )
        ).scalars().all()
        channel_ids.update(links)
    return channel_ids


async def _followed_person_slugs(
    session: AsyncSession, operator_id: str
) -> dict[str, UUID]:
    follows = (
        await session.execute(
            select(FollowDB).where(
                and_(
                    FollowDB.operator_id == operator_id,
                    FollowDB.subject_type == "PERSON",
                    FollowDB.deleted_at.is_(None),
                    FollowDB.muted.is_(False),
                )
            )
        )
    ).scalars().all()
    person_ids = [f.subject_id for f in follows]
    if not person_ids:
        return {}
    persons = (
        await session.execute(
            select(PersonDB).where(
                and_(PersonDB.id.in_(person_ids), PersonDB.deleted_at.is_(None))
            )
        )
    ).scalars().all()
    return {p.slug: p.id for p in persons if p.slug}


def _recency_score(published_at: datetime, window: str) -> float:
    days = _WINDOW_DAYS.get(window, 7)
    age = (datetime.now(timezone.utc) - published_at).total_seconds() / 86400
    if age < 0:
        age = 0
    return max(0.0, 1.0 - age / days)


def _genre_score(tags: list[str], prefs: OperatorPreferences) -> float:
    if not tags:
        return 0.0
    weights = prefs.genre_weights or DEFAULT_GENRE_WEIGHTS
    matched = [weights.get(t.lower(), 0.0) for t in tags if t.lower() in weights]
    if not matched:
        return 0.0
    return sum(matched) / len(matched)


def _score_candidate(c: _Candidate, prefs: OperatorPreferences, window: str) -> float:
    if not prefs.source_enabled.get(c.source, True):
        return -1.0
    trust = prefs.source_trust.get(c.source, 0.5)
    return (
        0.35 * _recency_score(c.published_at, window)
        + 0.30 * c.follow_boost
        + 0.15 * _genre_score(c.tags, prefs)
        + 0.10 * trust
        + 0.10 * min(1.0, c.community_weight)
    )


def _ukf_dnb_tags(channel: ChannelDB, title: str, description: str | None) -> list[str]:
    """Tag UKF-family uploads and DnB keyword matches for genre ranking."""
    tags: list[str] = []
    handle = (channel.handle or "").lower()
    platform = (channel.platform or "").lower()
    if handle.startswith("@ukf") or "ukf.com/read" in handle:
        tags.append("drum-and-bass")
    if platform == "rss" and "ukf.com" in handle:
        tags.append("drum-and-bass")
    text = f"{title} {description or ''}".lower()
    if any(kw in text for kw in ("drum & bass", "drum and bass", " dnb", "dnb ", "jungle", "neuro")):
        if "drum-and-bass" not in tags:
            tags.append("drum-and-bass")
    return tags


async def _creator_intel_candidates(
    session: AsyncSession,
    operator_id: str,
    since: datetime,
    channel_ids: set[UUID],
    artist_slug: str | None,
    person_slugs: dict[str, UUID],
) -> list[_Candidate]:
    if not channel_ids:
        return []
    if artist_slug and artist_slug not in person_slugs:
        return []

    stmt = (
        select(VideoDB, ChannelDB)
        .join(ChannelDB, VideoDB.channel_id == ChannelDB.id)
        .where(
            and_(
                VideoDB.channel_id.in_(channel_ids),
                VideoDB.published_at >= since,
            )
        )
        .order_by(VideoDB.published_at.desc())
        .limit(100)
    )
    rows = (await session.execute(stmt)).all()
    out: list[_Candidate] = []
    for video, channel in rows:
        source = channel.platform
        is_rss = channel.platform == "rss"
        tags = ["New Video"] if not is_rss else ["Editorial"]
        if channel.platform == "youtube":
            tags.append("Featured")
        tags.extend(_ukf_dnb_tags(channel, video.title, video.description))
        item_type = FeedItemType.EDITORIAL if is_rss else FeedItemType.NEW_VIDEO
        out.append(
            _Candidate(
                id=f"video:{video.id}",
                lane=FeedLane.FOLLOWED,
                type=item_type,
                source=source,
                title=video.title,
                subtitle=channel.display_name,
                tags=tags,
                artist_ids=[str(channel.id)],
                event_date=None,
                published_at=video.published_at,
                link=video.video_id if is_rss else f"/feeds/videos/{video.id}",
                attrs={
                    "thumbnail_url": video.thumbnail_url,
                    "channel_handle": channel.handle,
                },
                follow_boost=1.0,
            )
        )

    analysis_stmt = (
        select(FeedAnalysisDB, ChannelDB)
        .join(ChannelDB, FeedAnalysisDB.channel_id == ChannelDB.id)
        .where(
            and_(
                FeedAnalysisDB.channel_id.in_(channel_ids),
                FeedAnalysisDB.generated_at >= since,
            )
        )
        .order_by(FeedAnalysisDB.generated_at.desc())
        .limit(50)
    )
    for analysis, channel in (await session.execute(analysis_stmt)).all():
        out.append(
            _Candidate(
                id=f"release:{analysis.id}",
                lane=FeedLane.FOLLOWED,
                type=FeedItemType.NEW_RELEASE,
                source=channel.platform,
                title=f"Release {analysis.to_tag}",
                subtitle=channel.display_name,
                tags=["New LP", analysis.to_tag],
                artist_ids=[str(channel.id)],
                event_date=None,
                published_at=analysis.generated_at,
                link=analysis.release_url,
                attrs={"from_tag": analysis.from_tag, "to_tag": analysis.to_tag},
                follow_boost=1.0,
            )
        )
    return out


async def _ontology_candidates(
    since: datetime,
    person_slugs: dict[str, UUID],
    artist_slug: str | None,
    prefs: OperatorPreferences,
) -> list[_Candidate]:
    dsn = os.getenv("MAYA_ONTOLOGY_DSN")
    if not dsn:
        return []
    try:
        import asyncpg
    except ImportError:
        return []

    slugs = list(person_slugs.keys())
    if artist_slug:
        slugs = [artist_slug] if artist_slug in person_slugs or artist_slug else slugs
    if not slugs and not artist_slug:
        return []

    conn = await asyncpg.connect(dsn)
    try:
        query = """
            SELECT n.id, n.label, n.slug, n.domain, n.node_type, n.attrs, n.updated_at
            FROM ontology_node n
            WHERE n.domain = 'music'
              AND n.node_type IN ('track', 'release')
              AND (
                COALESCE(n.attrs->>'release_date', '') != ''
                OR COALESCE(n.attrs->>'first_seen_at', '') != ''
              )
            ORDER BY n.updated_at DESC
            LIMIT 80
        """
        rows = await conn.fetch(query)
    finally:
        await conn.close()

    out: list[_Candidate] = []
    for row in rows:
        attrs = row["attrs"] or {}
        if isinstance(attrs, str):
            attrs = json.loads(attrs)
        pub_raw = attrs.get("release_date") or attrs.get("first_seen_at")
        if not pub_raw:
            continue
        try:
            published_at = datetime.fromisoformat(str(pub_raw).replace("Z", "+00:00"))
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
        except ValueError:
            published_at = row["updated_at"]
        if published_at < since:
            continue

        artist_slug_row = attrs.get("artist_slug") or row["slug"]
        if artist_slug and artist_slug_row != artist_slug:
            continue
        if slugs and artist_slug_row not in slugs:
            continue

        genre = attrs.get("genre", "")
        tags = ["New LP"]
        if genre:
            tags.append(str(genre).lower())

        source = attrs.get("source", "discogs")
        if not prefs.source_enabled.get(source, True):
            continue

        out.append(
            _Candidate(
                id=f"ontology:{row['id']}",
                lane=FeedLane.FOLLOWED if artist_slug_row in person_slugs else FeedLane.ALGORITHMIC,
                type=FeedItemType.NEW_RELEASE,
                source=source,
                title=row["label"],
                subtitle=attrs.get("artist"),
                tags=tags,
                artist_ids=[str(row["id"])],
                event_date=None,
                published_at=published_at,
                link=attrs.get("url"),
                attrs=attrs,
                follow_boost=1.0 if artist_slug_row in person_slugs else 0.3,
                community_weight=float(attrs.get("community_weight", 0)),
            )
        )
    return out


async def _knowledge_item_candidates(
    session: AsyncSession,
    operator_id: str,
    since: datetime,
    person_slugs: dict[str, UUID],
    artist_slug: str | None,
    prefs: OperatorPreferences,
) -> list[_Candidate]:
    if not prefs.source_enabled.get("email_newsletter", True):
        return []

    stmt = (
        select(KnowledgeItemDB)
        .where(
            and_(
                KnowledgeItemDB.operator_id == operator_id,
                KnowledgeItemDB.received_at >= since,
            )
        )
        .order_by(KnowledgeItemDB.received_at.desc())
        .limit(50)
    )
    rows = (await session.execute(stmt)).scalars().all()
    out: list[_Candidate] = []
    for row in rows:
        if artist_slug and row.artist_slug != artist_slug:
            continue
        artifact_id = row.html_artifact_key.split("/")[-1].replace(".html", "")
        from maya_gateway.services.artifact_store import artifact_public_url

        follow_boost = 1.0 if row.artist_slug in person_slugs else 0.4
        tags = list(row.tags or [])
        if "music" not in tags:
            tags.insert(0, "music")
        out.append(
            _Candidate(
                id=f"knowledge:{row.id}",
                lane=FeedLane.FOLLOWED if row.artist_slug in person_slugs else FeedLane.ALGORITHMIC,
                type=FeedItemType.EDITORIAL,
                source="email_newsletter",
                title=row.title,
                subtitle=row.artist_display,
                tags=tags,
                artist_ids=[str(row.id)],
                event_date=row.release_date,
                published_at=row.received_at,
                link=artifact_public_url(artifact_id),
                attrs={
                    "knowledge_item_id": str(row.id),
                    "artist_slug": row.artist_slug,
                    "artist_display": row.artist_display,
                    "track": row.track,
                    "album": row.album,
                    "promo": row.promo,
                    "handwritten_note": row.handwritten_note,
                    "brand_color": row.brand_color,
                    "html_artifact_url": artifact_public_url(artifact_id),
                },
                follow_boost=follow_boost,
            )
        )
    return out


async def get_inbox_summary(
    session: AsyncSession,
    operator_id: str,
    *,
    window: str = "7d",
) -> InboxSummaryResponse:
    since = _window_start(window)
    rows = (
        await session.execute(
            select(KnowledgeItemDB)
            .where(
                and_(
                    KnowledgeItemDB.operator_id == operator_id,
                    KnowledgeItemDB.received_at >= since,
                )
            )
            .order_by(KnowledgeItemDB.received_at.desc())
        )
    ).scalars().all()

    grouped: dict[str, dict] = {}
    for row in rows:
        key = row.artist_slug
        if key not in grouped:
            grouped[key] = {
                "artist_slug": row.artist_slug,
                "artist_display": row.artist_display,
                "count": 0,
                "brand_color": row.brand_color,
                "latest_title": row.title,
            }
        grouped[key]["count"] += 1

    artists = [
        InboxArtistSummary(**data)
        for data in sorted(grouped.values(), key=lambda d: -d["count"])
    ]
    return InboxSummaryResponse(total=len(rows), artists=artists)


async def rank_feed(
    session: AsyncSession,
    operator_id: str,
    *,
    window: str = "7d",
    cursor: str | None = None,
    limit: int = 20,
    lane: str | None = None,
    artist_slug: str | None = None,
) -> FeedResponse:
    prefs = await get_or_create_preferences(session, operator_id)
    since = _window_start(window)
    channel_ids = await _followed_channel_ids(session, operator_id)
    person_slugs = await _followed_person_slugs(session, operator_id)

    candidates: list[_Candidate] = []
    candidates.extend(
        await _creator_intel_candidates(
            session, operator_id, since, channel_ids, artist_slug, person_slugs
        )
    )
    candidates.extend(
        await _ontology_candidates(since, person_slugs, artist_slug, prefs)
    )
    candidates.extend(
        await _knowledge_item_candidates(
            session, operator_id, since, person_slugs, artist_slug, prefs
        )
    )

    scored: list[tuple[float, _Candidate]] = []
    for c in candidates:
        score = _score_candidate(c, prefs, window)
        if score < 0:
            continue
        if lane and c.lane.value != lane:
            continue
        scored.append((score, c))

    scored.sort(key=lambda x: (-x[0], -x[1].published_at.timestamp()))
    items: list[FeedItem] = []
    for score, c in scored:
        items.append(
            FeedItem(
                id=c.id,
                lane=c.lane,
                type=c.type,
                source=c.source,
                title=c.title,
                subtitle=c.subtitle,
                tags=c.tags,
                artist_ids=c.artist_ids,
                event_date=c.event_date,
                score=round(score, 4),
                published_at=c.published_at,
                link=c.link,
                attrs=c.attrs,
            )
        )

    if cursor:
        decoded = _decode_cursor(cursor)
        if decoded:
            cut_time, cut_id = decoded
            filtered: list[FeedItem] = []
            passed = False
            for item in items:
                if passed:
                    filtered.append(item)
                elif item.published_at < cut_time or (
                    item.published_at == cut_time and item.id != cut_id
                ):
                    passed = True
                    filtered.append(item)
            items = filtered

    page = items[:limit]
    next_cursor = None
    if len(items) > limit and page:
        last = page[-1]
        next_cursor = _encode_cursor(last.published_at, last.id)

    return FeedResponse(
        items=page,
        next_cursor=next_cursor,
        window=window,
        total=len(scored),
    )


async def get_collection_summary(
    session: AsyncSession, operator_id: str
) -> CollectionSummaryDB | None:
    return (
        await session.execute(
            select(CollectionSummaryDB).where(
                CollectionSummaryDB.operator_id == operator_id
            )
        )
    ).scalar_one_or_none()
