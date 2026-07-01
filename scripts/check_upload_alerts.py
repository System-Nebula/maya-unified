#!/usr/bin/env python3
"""Health check for MissKatie / homepage upload-alert pipeline.

Exit 0 when ready; exit 1 with actionable messages otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import httpx
from maya_db import (
    Channel as ChannelDB,
    Follow as FollowDB,
    Person as PersonDB,
    Subscription as SubscriptionDB,
    get_async_session,
)
from sqlalchemy import select

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://maya:maya@localhost:5433/maya_public",
)
GATEWAY_URL = os.getenv("MAYA_GATEWAY_URL", "http://localhost:8090")
OPERATOR_ID = os.getenv("MAYA_OPERATOR_ID", "local")
DEFAULT_PERSON_SLUG = "misskatie"


async def check_db(person_slug: str) -> list[str]:
    errors: list[str] = []
    warnings: list[str] = []
    async for session in get_async_session():
        person = (
            await session.execute(
                select(PersonDB).where(PersonDB.slug == person_slug)
            )
        ).scalar_one_or_none()
        if person is None:
            errors.append(
                f"person slug={person_slug!r} not found — run make seed-profiles"
            )
            return errors

        follow = (
            await session.execute(
                select(FollowDB).where(
                    FollowDB.operator_id == OPERATOR_ID,
                    FollowDB.subject_type == "PERSON",
                    FollowDB.subject_id == person.id,
                    FollowDB.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if follow is None:
            errors.append(f"no active follow row for {person_slug}")
        elif not follow.notify_homepage:
            errors.append("follow.notify_homepage is false")

        yt = (
            await session.execute(
                select(ChannelDB).where(
                    ChannelDB.platform == "youtube",
                    ChannelDB.handle == "@MissKatie",
                )
            )
        ).scalar_one_or_none()
        if yt is None:
            errors.append("YouTube channel @MissKatie not in feed_channels")
            return errors

        if not yt.platform_id or yt.platform_id.startswith("@"):
            errors.append(
                f"YouTube platform_id unresolved ({yt.platform_id!r}) — run make repair-youtube-channels"
            )
        if not yt.feed_url:
            errors.append("YouTube feed_url missing — run make repair-youtube-channels")

        sub = (
            await session.execute(
                select(SubscriptionDB).where(SubscriptionDB.channel_id == yt.id)
            )
        ).scalar_one_or_none()
        if sub is None or not sub.enabled:
            errors.append("no enabled feed_subscriptions row for YouTube channel")

        if yt.last_fetched_at is None:
            warnings.append("last_fetched_at is NULL — ingest poll has never run (make ingest-poll)")
        elif sub is not None:
            cadence = sub.cadence or "weekly"
            delta = {
                "hourly": timedelta(hours=2),
                "daily": timedelta(days=2),
                "weekly": timedelta(days=14),
            }.get(cadence, timedelta(days=14))
            if yt.last_fetched_at + delta < datetime.now(timezone.utc):
                warnings.append(
                    f"last_fetched_at stale ({yt.last_fetched_at.isoformat()}) for cadence={cadence}"
                )

    for w in warnings:
        print(f"WARN: {w}", file=sys.stderr)
    return errors


async def check_gateway_sse() -> list[str]:
    errors: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            async with client.stream(
                "GET",
                f"{GATEWAY_URL.rstrip('/')}/api/notifications/stream",
            ) as resp:
                if resp.status_code != 200:
                    errors.append(f"gateway SSE returned {resp.status_code}")
                    return errors
                async for line in resp.aiter_lines():
                    if line.startswith("event: hello"):
                        return errors
                    break
            errors.append("gateway SSE did not emit hello event")
    except httpx.HTTPError as exc:
        errors.append(f"gateway unreachable at {GATEWAY_URL}: {exc}")
    return errors


async def run(*, skip_gateway: bool, person_slug: str) -> int:
    os.environ.setdefault("DATABASE_URL", DATABASE_URL)
    errors = await check_db(person_slug)
    if not skip_gateway:
        errors.extend(await check_gateway_sse())
    if errors:
        for msg in errors:
            print(f"FAIL: {msg}", file=sys.stderr)
        return 1
    print("OK: upload alerts pipeline looks healthy")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Check upload-alert pipeline health")
    parser.add_argument(
        "--person-slug",
        default=os.getenv("CHECK_PERSON_SLUG", DEFAULT_PERSON_SLUG),
        help=f"Person slug to verify (default: CHECK_PERSON_SLUG or {DEFAULT_PERSON_SLUG})",
    )
    parser.add_argument(
        "--skip-gateway",
        action="store_true",
        help="Only check database state (skip SSE probe)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(skip_gateway=args.skip_gateway, person_slug=args.person_slug)))


if __name__ == "__main__":
    main()
