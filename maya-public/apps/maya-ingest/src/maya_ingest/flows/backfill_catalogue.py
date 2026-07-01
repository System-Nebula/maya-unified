"""Back-catalogue indexer: walk a channel's full upload history.

Idempotent: skips video_ids already present. Resumable: stores the
in-progress pageToken in ``feed_channels.profile_links`` under the
``_archive_cursor`` key, and stamps ``archive_indexed_at`` when done.

Daily budget: by default 4 pages (= 200 videos) per run. With a once-a-day
schedule this clears ~800 videos in 4 days, leaving plenty of YouTube API
quota for the live atom-poll path.
"""

from __future__ import annotations

from datetime import datetime, timezone

from maya_contracts import Platform
from maya_db import Channel as ChannelDB, Video as VideoDB, get_async_session
from prefect import flow, get_run_logger
from sqlalchemy import select

from maya_ingest.tasks.yt_catalogue import fetch_page


@flow(name="backfill-catalogue")
async def backfill_catalogue(
    channel_id: str, max_pages_per_run: int = 4
) -> dict[str, int]:
    """Insert any missing archive videos for ``channel_id``.

    Returns counts of new videos inserted and pages walked. Stops early when
    the platform returns no nextPageToken — at that point we also stamp
    ``archive_indexed_at`` so future runs short-circuit.
    """
    logger = get_run_logger()
    inserted = 0
    pages_walked = 0

    async for session in get_async_session():
        channel = await session.get(ChannelDB, channel_id)
        if channel is None:
            logger.warning("no such channel %s", channel_id)
            return {"inserted": 0, "pages": 0}
        if Platform(channel.platform) != Platform.YOUTUBE:
            logger.info("backfill not supported for platform %s", channel.platform)
            return {"inserted": 0, "pages": 0}
        if channel.archive_indexed_at is not None:
            logger.info("channel %s archive already complete", channel.handle)
            return {"inserted": 0, "pages": 0}

        cursor = (channel.profile_links or [])
        token = None
        for link in cursor:
            if link.get("_archive_cursor"):
                token = link["_archive_cursor"]
                break

        while pages_walked < max_pages_per_run:
            page = await fetch_page(channel.platform_id, page_token=token)
            pages_walked += 1
            if not page.entries:
                break

            existing = set(
                (
                    await session.execute(
                        select(VideoDB.video_id).where(
                            VideoDB.channel_id == channel.id,
                            VideoDB.video_id.in_([e.video_id for e in page.entries]),
                        )
                    )
                )
                .scalars()
                .all()
            )

            for entry in page.entries:
                if entry.video_id in existing:
                    continue
                session.add(
                    VideoDB(
                        channel_id=channel.id,
                        video_id=entry.video_id,
                        title=entry.title,
                        description=entry.description,
                        published_at=entry.published_at,
                        thumbnail_url=entry.thumbnail_url,
                        source_phase="archive",
                    )
                )
                inserted += 1

            if page.next_page_token:
                token = page.next_page_token
            else:
                token = None
                break

        # Persist cursor state.
        links = [l for l in (channel.profile_links or []) if not l.get("_archive_cursor")]
        if token is None:
            channel.archive_indexed_at = datetime.now(timezone.utc)
        else:
            links.append({"_archive_cursor": token})
        channel.profile_links = links

        await session.commit()
    logger.info(
        "backfill channel=%s inserted=%d pages=%d", channel_id, inserted, pages_walked
    )
    return {"inserted": inserted, "pages": pages_walked}
