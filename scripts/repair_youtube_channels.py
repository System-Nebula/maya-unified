#!/usr/bin/env python3
"""Repair YouTube feed_channels rows missing UC… id or Atom feed_url.

Usage:
  make repair-youtube-channels
  uv run --with httpx python scripts/repair_youtube_channels.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio

from maya_contracts import Platform
from maya_db import Channel as ChannelDB, get_async_session
from maya_feeds.youtube import YouTubeAdapter
from maya_gateway.services.follow_enrich import apply_channel_metadata, needs_youtube_enrich
from sqlalchemy import or_, select


async def repair(*, dry_run: bool = False) -> int:
    adapter = YouTubeAdapter()
    repaired = 0
    async for session in get_async_session():
        stmt = select(ChannelDB).where(
            ChannelDB.platform == Platform.YOUTUBE.value,
            or_(
                ChannelDB.feed_url.is_(None),
                ChannelDB.platform_id.like("@%"),
            ),
        )
        channels = (await session.execute(stmt)).scalars().all()
        for channel in channels:
            if not needs_youtube_enrich(
                platform=channel.platform,
                platform_id=channel.platform_id,
                feed_url=channel.feed_url,
            ):
                continue
            handle = channel.handle or channel.platform_id
            print(f"repair {channel.id} handle={handle!r} platform_id={channel.platform_id!r}")
            if dry_run:
                repaired += 1
                continue
            metadata = await adapter.resolve_channel(handle)
            apply_channel_metadata(channel, metadata)
            repaired += 1
        if not dry_run:
            await session.commit()
    return repaired


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair YouTube channel metadata in feed_channels")
    parser.add_argument("--dry-run", action="store_true", help="Print rows that would be repaired")
    args = parser.parse_args()
    count = asyncio.run(repair(dry_run=args.dry_run))
    print(f"{'would repair' if args.dry_run else 'repaired'} {count} channel(s)")


if __name__ == "__main__":
    main()
