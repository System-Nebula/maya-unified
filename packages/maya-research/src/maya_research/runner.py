"""Shared research run loader and executor."""

from __future__ import annotations

from uuid import UUID

from maya_contracts import ResearchDepth, ResearchPlan, ResearchRunStatus
from maya_db import ResearchRun as ResearchRunDB, get_async_session
from maya_research.agent.graph import (
    run_research,
    run_research_execution,
    run_research_planning,
)
from maya_research.agent.state import ResearchState
from maya_research.storage.run_repository import update_run_status


async def load_state(run_id: str) -> ResearchState:
    async for session in get_async_session():
        row = await session.get(ResearchRunDB, UUID(run_id))
        if row is None:
            raise ValueError(f"research run {run_id} not found")
        plan = ResearchPlan.model_validate(row.plan) if row.plan else None
        return ResearchState(
            run_id=str(row.id),
            brief=row.brief,
            depth=row.depth,
            source_mask=list(row.source_mask or []),
            seed_urls=list(row.seed_urls or []),
            operator_id=row.operator_id,
            discord_thread_id=row.discord_thread_id,
            prior_research_id=(row.prior_research_ids or [None])[0]
            if row.prior_research_ids
            else None,
            plan=plan,
            plan_approved=row.plan_approved,
            errors=list(row.errors or []),
            progress=list(row.progress or []),
        )
    raise ValueError(f"research run {run_id} not found")


async def execute_run(run_id: str, *, execution_only: bool = False) -> ResearchState:
    state = await load_state(run_id)
    depth = state.get("depth", "shallow")

    if execution_only:
        await update_run_status(run_id, ResearchRunStatus.EXECUTING)
        return await run_research_execution(state)
    if depth == ResearchDepth.DEEP.value and not state.get("plan_approved"):
        await update_run_status(run_id, ResearchRunStatus.PLANNING)
        return await run_research_planning(state)

    await update_run_status(run_id, ResearchRunStatus.EXECUTING)
    return await run_research(state)
