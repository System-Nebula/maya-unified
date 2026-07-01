"""Research run persistence helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from maya_contracts import (
    ResearchPlan,
    ResearchProgressEvent,
    ResearchReport,
    ResearchRunStatus,
)
from maya_db import ResearchRun as ResearchRunDB, get_async_session


async def append_progress(
    run_id: str,
    stage: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> None:
    event = ResearchProgressEvent(
        stage=stage,
        message=message,
        timestamp=datetime.now(timezone.utc),
        details=details or {},
    )
    async for session in get_async_session():
        row = await session.get(ResearchRunDB, UUID(run_id))
        if row is None:
            return
        progress = list(row.progress or [])
        progress.append(event.model_dump(mode="json"))
        row.progress = progress
        await session.commit()
        break


async def update_run_status(run_id: str, status: ResearchRunStatus) -> None:
    async for session in get_async_session():
        row = await session.get(ResearchRunDB, UUID(run_id))
        if row is None:
            return
        row.status = status.value
        await session.commit()
        break


async def save_plan(run_id: str, plan: ResearchPlan, *, approved: bool) -> None:
    async for session in get_async_session():
        row = await session.get(ResearchRunDB, UUID(run_id))
        if row is None:
            return
        row.plan = plan.model_dump(mode="json")
        row.plan_approved = approved
        row.status = (
            ResearchRunStatus.EXECUTING.value
            if approved
            else ResearchRunStatus.AWAITING_APPROVAL.value
        )
        await session.commit()
        break


async def save_report(
    run_id: str,
    report: ResearchReport,
    *,
    artifact_id: str | None,
    artifact_key: str | None,
    errors: list[str],
) -> None:
    async for session in get_async_session():
        row = await session.get(ResearchRunDB, UUID(run_id))
        if row is None:
            return
        row.report = report.model_dump(mode="json")
        row.artifact_id = artifact_id
        row.artifact_key = artifact_key
        row.errors = errors
        row.status = (
            ResearchRunStatus.COMPLETE.value
            if not errors
            else ResearchRunStatus.FAILED.value
        )
        row.completed_at = datetime.now(timezone.utc)
        await session.commit()
        break
