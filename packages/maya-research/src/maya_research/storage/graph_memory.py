"""Prior research recall from maya-db and ontology graph."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from maya_contracts import PriorResearchRef, ResearchRunStatus
from maya_db import ResearchRun as ResearchRunDB, get_async_session
from maya_research.storage.embedding_cache import cosine_similarity, get_embedder
from sqlalchemy import select


async def find_prior_research(
    brief: str,
    *,
    operator_id: str = "local",
    limit: int = 5,
    threshold: float = 0.3,
) -> list[PriorResearchRef]:
    embedder = get_embedder()
    brief_vec = (await embedder.embed([brief]))[0]
    refs: list[PriorResearchRef] = []

    async for session in get_async_session():
        q = (
            select(ResearchRunDB)
            .where(ResearchRunDB.operator_id == operator_id)
            .where(ResearchRunDB.status == ResearchRunStatus.COMPLETE.value)
            .order_by(ResearchRunDB.completed_at.desc())
            .limit(50)
        )
        rows = (await session.execute(q)).scalars().all()
        for row in rows:
            score = _similarity_for_run(row, brief, brief_vec)
            if score < threshold and brief.lower() not in row.brief.lower():
                continue
            report = row.report or {}
            refs.append(
                PriorResearchRef(
                    id=str(row.id),
                    title=report.get("title") or row.brief[:80],
                    brief=row.brief,
                    summary=report.get("executive_summary") or "",
                    researched_at=row.completed_at or row.updated_at,
                    similarity_score=score,
                )
            )
        break

    refs.sort(key=lambda r: r.similarity_score, reverse=True)
    return refs[:limit]


def _similarity_for_run(row: ResearchRunDB, brief: str, brief_vec: list[float]) -> float:
    if row.brief_embedding is not None:
        try:
            vec = list(row.brief_embedding)
            return cosine_similarity(brief_vec, vec)
        except Exception:
            pass
    overlap = len(set(brief.lower().split()) & set(row.brief.lower().split()))
    return min(1.0, overlap / max(len(brief.split()), 1))


async def load_graph_recall(prior: list[PriorResearchRef]) -> list[dict]:
    return [
        {
            "id": p.id,
            "title": p.title,
            "summary": p.summary,
            "researched_at": p.researched_at.isoformat(),
        }
        for p in prior
    ]


async def should_use_delta_mode(
    prior: list[PriorResearchRef],
    depth: str,
    *,
    min_similarity: float = 0.75,
) -> tuple[bool, datetime | None]:
    if depth != "shallow" or not prior:
        return False, None
    best = prior[0]
    if best.similarity_score < min_similarity:
        return False, None
    return True, best.researched_at
