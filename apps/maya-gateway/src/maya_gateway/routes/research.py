"""Research agent API — create runs, approve plans, poll progress, fetch artifacts."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from maya_contracts import (
    ApproveResearchPlanRequest,
    CreateResearchRunRequest,
    PaginatedResponse,
    ResearchRun,
)
from maya_db import ResearchRun as ResearchRunDB, get_async_session
from sqlalchemy.ext.asyncio import AsyncSession

from maya_gateway.services import research_service

if TYPE_CHECKING:
    pass

router = APIRouter(prefix="/api/research", tags=["research"])

DEFAULT_OPERATOR_ID = "local"
_STREAM_POLL_SECONDS = 3.0


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid uuid") from exc


@router.post("/runs", response_model=ResearchRun, status_code=202)
async def create_research_run(req: CreateResearchRunRequest):
    try:
        return await research_service.create_run(req)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/runs", response_model=PaginatedResponse[ResearchRun])
async def list_research_runs(
    limit: int = 50,
    offset: int = 0,
    operator_id: str = DEFAULT_OPERATOR_ID,
):
    return await research_service.list_runs(
        operator_id=operator_id, limit=limit, offset=offset
    )


@router.get("/runs/{run_id}", response_model=ResearchRun)
async def get_research_run(run_id: str):
    run = await research_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="research run not found")
    return run


@router.post("/runs/{run_id}/approve", response_model=ResearchRun)
async def approve_research_plan(run_id: str, req: ApproveResearchPlanRequest):
    try:
        return await research_service.approve_run(run_id, req)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/progress")
async def stream_research_progress(
    run_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    async def event_generator():
        last_len = 0
        while True:
            row = await session.get(ResearchRunDB, _uuid(run_id))
            if row is None:
                yield f"data: {json.dumps({'error': 'not found'})}\n\n"
                break
            progress = row.progress or []
            if len(progress) > last_len:
                for item in progress[last_len:]:
                    yield f"data: {json.dumps(item)}\n\n"
                last_len = len(progress)
            if row.status in ("complete", "failed", "awaiting_approval"):
                yield f"data: {json.dumps({'stage': 'terminal', 'status': row.status})}\n\n"
                if row.status != "awaiting_approval":
                    break
            import asyncio

            await asyncio.sleep(_STREAM_POLL_SECONDS)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/artifacts/{artifact_id}")
async def get_research_artifact(artifact_id: str):
    loaded = research_service.load_artifact_bytes(artifact_id)
    if loaded is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    content, content_type = loaded
    return Response(content=content, media_type=content_type)
