"""Hourly embedding batch + similarity materialisation."""

from __future__ import annotations

from maya_db import (
    Comment as CommentDB,
    Video as VideoDB,
    VideoSimilarity as SimilarityDB,
    get_async_session,
)
from prefect import flow, get_run_logger
from sqlalchemy import select

from maya_ingest.config import load_config
from maya_ingest.tasks.embeddings import get_embedder


@flow(name="embed-pending")
async def embed_pending(batch_size: int = 128) -> dict[str, int]:
    """Embed any video/comment rows missing vectors. Returns counts per type."""
    logger = get_run_logger()
    cfg = load_config()
    embedder = get_embedder(cfg.embed_backend)
    counts = {"videos": 0, "comments": 0, "similarity": 0}

    async for session in get_async_session():
        # Videos
        vids = (
            await session.execute(
                select(VideoDB).where(VideoDB.embedding.is_(None)).limit(batch_size)
            )
        ).scalars().all()
        if vids:
            texts = [f"{v.title}\n{(v.description or '')[:500]}" for v in vids]
            vectors = await embedder.embed(texts)
            for v, vec in zip(vids, vectors):
                v.embedding = vec
            counts["videos"] = len(vids)

        # Comments
        cmts = (
            await session.execute(
                select(CommentDB).where(CommentDB.embedding.is_(None)).limit(batch_size)
            )
        ).scalars().all()
        if cmts:
            vectors = await embedder.embed([c.text for c in cmts])
            for c, vec in zip(cmts, vectors):
                c.embedding = vec
            counts["comments"] = len(cmts)

        await session.commit()

        # Materialise top-k similarity for newly embedded videos.
        for v in vids:
            try:
                from pgvector.sqlalchemy import Vector  # noqa: F401

                neighbours = (
                    await session.execute(
                        select(VideoDB.id, VideoDB.embedding.cosine_distance(v.embedding).label("d"))
                        .where(VideoDB.id != v.id)
                        .where(VideoDB.embedding.is_not(None))
                        .order_by("d")
                        .limit(10)
                    )
                ).all()
            except Exception:
                neighbours = []
            for other_id, distance in neighbours:
                score = 1.0 - float(distance)
                session.add(
                    SimilarityDB(video_a_id=v.id, video_b_id=other_id, score=score)
                )
                counts["similarity"] += 1
        await session.commit()
    logger.info("embed counts %s", counts)
    return counts
