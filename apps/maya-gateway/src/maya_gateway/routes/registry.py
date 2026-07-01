"""Model registry endpoints — backed by Postgres."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from maya_contracts import (
    EvalRun,
    ModelRelease,
    ModelReleaseCreate,
    ModelReleaseUpdate,
    PaginatedResponse,
)
from maya_db import EvalRun as EvalRunDB, ModelRelease as ModelReleaseDB, get_async_session
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/registry", tags=["registry"])


def _release_to_response(r: ModelReleaseDB) -> ModelRelease:
    return ModelRelease(
        id=str(r.id),
        slug=r.slug,
        provider=r.provider,
        source_url=r.source_url,
        capability_family=r.capability_family,
        modality_in=r.modality_in,
        modality_out=r.modality_out,
        base_model=r.base_model,
        quantization=r.quantization,
        runtime=r.runtime,
        license=r.license,
        artifacts=r.artifacts,
        eval_status=r.eval_status,
        publisher_claims=r.publisher_claims,
        tags=r.tags,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _eval_to_response(e: EvalRunDB) -> EvalRun:
    return EvalRun(
        id=str(e.id),
        model_release_id=e.model_release_id,
        eval_suite=e.eval_suite,
        eval_type=e.eval_type,
        status=e.status,
        metrics=e.metrics,
        artifact_paths=e.artifact_paths,
        started_at=e.started_at,
        completed_at=e.completed_at,
    )


@router.get("/releases", response_model=PaginatedResponse[ModelRelease])
async def list_releases(
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    session: AsyncSession = Depends(get_async_session),
):
    stmt = select(ModelReleaseDB).order_by(ModelReleaseDB.created_at.desc())
    if status:
        stmt = stmt.where(ModelReleaseDB.eval_status == status)
    total_result = await session.execute(
        select(ModelReleaseDB).where(ModelReleaseDB.eval_status == status) if status else select(ModelReleaseDB)
    )
    total = len(total_result.scalars().all())
    result = await session.execute(stmt.offset(offset).limit(limit))
    items = [_release_to_response(r) for r in result.scalars().all()]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/releases/{release_id}", response_model=ModelRelease)
async def get_release(
    release_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    r = await session.get(ModelReleaseDB, release_id)
    if not r:
        raise HTTPException(status_code=404, detail="release not found")
    return _release_to_response(r)


@router.post("/releases", response_model=ModelRelease)
async def create_release(
    req: ModelReleaseCreate,
    session: AsyncSession = Depends(get_async_session),
):
    release = ModelReleaseDB(
        slug=req.slug,
        provider=req.provider,
        source_url=req.source_url,
        capability_family=req.capability_family.value,
        modality_in=[m.value for m in req.modality_in],
        modality_out=[m.value for m in req.modality_out],
        base_model=req.base_model,
        quantization=req.quantization,
        runtime=req.runtime,
        license=req.license,
        artifacts=[a.model_dump() for a in req.artifacts],
        tags=req.tags,
    )
    session.add(release)
    await session.flush()
    return _release_to_response(release)


@router.patch("/releases/{release_id}", response_model=ModelRelease)
async def update_release(
    release_id: str,
    req: ModelReleaseUpdate,
    session: AsyncSession = Depends(get_async_session),
):
    r = await session.get(ModelReleaseDB, release_id)
    if not r:
        raise HTTPException(status_code=404, detail="release not found")
    if req.eval_status is not None:
        r.eval_status = req.eval_status.value
    if req.publisher_claims is not None:
        r.publisher_claims = req.publisher_claims
    if req.tags is not None:
        r.tags = req.tags
    await session.flush()
    return _release_to_response(r)


@router.get("/evals", response_model=PaginatedResponse[EvalRun])
async def list_evals(
    limit: int = 50,
    offset: int = 0,
    model_release_id: str | None = None,
    session: AsyncSession = Depends(get_async_session),
):
    stmt = select(EvalRunDB).order_by(EvalRunDB.created_at.desc())
    if model_release_id:
        stmt = stmt.where(EvalRunDB.model_release_id == model_release_id)
    total_result = await session.execute(
        select(EvalRunDB).where(EvalRunDB.model_release_id == model_release_id)
        if model_release_id else select(EvalRunDB)
    )
    total = len(total_result.scalars().all())
    result = await session.execute(stmt.offset(offset).limit(limit))
    items = [_eval_to_response(e) for e in result.scalars().all()]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)
