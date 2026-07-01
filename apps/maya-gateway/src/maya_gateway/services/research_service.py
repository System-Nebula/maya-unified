"""Research run orchestration service."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from maya_contracts import (
    ApproveResearchPlanRequest,
    CreateResearchRunRequest,
    PaginatedResponse,
    PriorResearchRef,
    ResearchDepth,
    ResearchPlan,
    ResearchProgressEvent,
    ResearchReport,
    ResearchRun,
    ResearchRunStatus,
    ResearchSourceKind,
)
from maya_db import ResearchRun as ResearchRunDB, get_async_session
from maya_research.storage.artifacts import artifact_public_url, load_markdown
from sqlalchemy import func, select


def _to_response(row: ResearchRunDB) -> ResearchRun:
    plan = ResearchPlan.model_validate(row.plan) if row.plan else None
    report = ResearchReport.model_validate(row.report) if row.report else None
    progress = [
        ResearchProgressEvent.model_validate(p) for p in (row.progress or [])
    ]
    prior = [PriorResearchRef.model_validate(p) for p in (row.prior_research or [])]
    return ResearchRun(
        id=str(row.id),
        brief=row.brief,
        depth=ResearchDepth(row.depth),
        source_mask=[ResearchSourceKind(s) for s in (row.source_mask or [])],
        status=ResearchRunStatus(row.status),
        plan=plan,
        plan_approved=row.plan_approved,
        prior_research=prior,
        report=report,
        artifact_url=artifact_public_url(row.artifact_id) if row.artifact_id else None,
        progress=progress,
        errors=list(row.errors or []),
        operator_id=row.operator_id,
        discord_thread_id=row.discord_thread_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
    )


async def create_run(req: CreateResearchRunRequest) -> ResearchRun:
    sources = req.sources or [
        ResearchSourceKind.WEB,
        ResearchSourceKind.REDDIT,
        ResearchSourceKind.LOCAL,
        ResearchSourceKind.GRAPH,
    ]
    async for session in get_async_session():
        row = ResearchRunDB(
            operator_id=req.operator_id,
            brief=req.brief,
            depth=req.depth.value,
            source_mask=[s.value for s in sources],
            seed_urls=req.seed_urls,
            discord_thread_id=req.discord_thread_id,
            status=ResearchRunStatus.PENDING.value,
            prior_research_ids=[req.prior_research_id] if req.prior_research_id else [],
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        run = _to_response(row)
        break

    asyncio.create_task(_kickoff_flow(str(run.id), execution_only=False))
    return run


async def approve_run(run_id: str, req: ApproveResearchPlanRequest) -> ResearchRun:
    async for session in get_async_session():
        row = await session.get(ResearchRunDB, UUID(run_id))
        if row is None:
            raise ValueError("run not found")
        if not req.approved:
            row.status = ResearchRunStatus.FAILED.value
            row.errors = list(row.errors or []) + ["plan rejected"]
            await session.commit()
            return _to_response(row)
        row.plan_approved = True
        row.status = ResearchRunStatus.EXECUTING.value
        await session.commit()
        run = _to_response(row)
        break

    asyncio.create_task(_kickoff_flow(run_id, execution_only=True))
    return run


async def get_run(run_id: str) -> ResearchRun | None:
    async for session in get_async_session():
        row = await session.get(ResearchRunDB, UUID(run_id))
        if row is None:
            return None
        return _to_response(row)
    return None


async def list_runs(
    *,
    operator_id: str = "local",
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResponse[ResearchRun]:
    async for session in get_async_session():
        filters = ResearchRunDB.operator_id == operator_id
        total = await session.scalar(
            select(func.count()).select_from(ResearchRunDB).where(filters)
        )
        rows = (
            await session.execute(
                select(ResearchRunDB)
                .where(filters)
                .order_by(ResearchRunDB.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
        return PaginatedResponse(
            items=[_to_response(r) for r in rows],
            total=int(total or 0),
            limit=limit,
            offset=offset,
        )
    return PaginatedResponse(items=[], total=0, limit=limit, offset=offset)


def load_artifact_bytes(artifact_id: str) -> tuple[bytes, str] | None:
    return load_markdown(artifact_id)


async def _kickoff_flow(run_id: str, *, execution_only: bool) -> None:
    from maya_research.runner import execute_run

    await execute_run(run_id, execution_only=execution_only)
