"""Persister node — write run results to DB and ontology graph."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from maya_db import (
    ResearchRun as ResearchRunDB,
    ResearchSentiment as ResearchSentimentDB,
    ResearchSource as ResearchSourceDB,
    ResearchTopicEmbedding as ResearchTopicEmbeddingDB,
    get_async_session,
)
from maya_research.agent.state import ResearchState
from maya_research.storage.embedding_cache import get_embedder
from maya_research.storage.graph_writer import persist_to_ontology
from maya_research.storage.run_repository import append_progress, save_report


async def persister_node(state: ResearchState) -> ResearchState:
    run_id = state.get("run_id", "")
    report = state.get("report")
    if not run_id or not report:
        return state

    errors = list(state.get("errors") or [])
    await save_report(
        run_id,
        report,
        artifact_id=state.get("artifact_id"),
        artifact_key=state.get("artifact_key"),
        errors=errors,
    )

    async for session in get_async_session():
        row = await session.get(ResearchRunDB, UUID(run_id))
        if row is None:
            break

        embedder = get_embedder()
        vec = (await embedder.embed([row.brief]))[0]
        row.brief_embedding = vec
        row.prior_research = [p.model_dump(mode="json") for p in state.get("prior_research") or []]
        row.delta_mode = bool(state.get("delta_mode"))
        if state.get("delta_since"):
            row.delta_since = datetime.fromisoformat(state["delta_since"])

        for p in state.get("fetched_pages") or []:
            session.add(
                ResearchSourceDB(
                    run_id=row.id,
                    url=p.url,
                    title=p.title,
                    credibility_score=p.credibility_score,
                    content_hash=p.content_hash,
                    artifact_key=p.artifact_key,
                    operator_visited=p.operator_visited,
                    fetched_at=p.fetched_at,
                )
            )
        for r in state.get("web_results") or []:
            session.add(
                ResearchSourceDB(
                    run_id=row.id,
                    url=r.url,
                    title=r.title,
                    snippet=r.snippet,
                    domain=r.domain,
                    credibility_score=r.credibility_score,
                    fetched_at=r.fetched_at,
                )
            )
        for b in state.get("reddit_bundles") or []:
            session.add(
                ResearchSentimentDB(
                    run_id=row.id,
                    subreddit=b.subreddit,
                    query=b.query,
                    payload=b.model_dump(mode="json"),
                    fetched_at=b.fetched_at,
                )
            )
        session.add(
            ResearchTopicEmbeddingDB(
                run_id=row.id,
                topic=row.brief,
                embedding=vec,
            )
        )
        await session.commit()
        break

    sources = [
        {"url": s.url, "title": s.title, "credibility_score": s.credibility_score}
        for s in report.sources
    ]
    await persist_to_ontology(run_id, report, sources=sources)

    await append_progress(run_id, "persister", "Research persisted", details={"status": "complete"})
    return state
