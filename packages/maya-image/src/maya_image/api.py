"""Minimal Imagine API for the public gateway (optional web UI)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from maya_image.service import get_image_service
from maya_image.workflows import list_workflows

router = APIRouter(prefix="/api/imagine", tags=["imagine"])

_CORRELATION_KEYS = (
    "corr_id",
    "trace_id",
    "workflow_id",
    "model_key",
    "surface",
    "fal_request_id",
    "comfyui_url",
)


@router.get("/health")
async def health() -> dict:
    try:
        from services.imagine.health import check_comfyui_health
    except ImportError:
        return {"status": "ok"}
    result = check_comfyui_health(run_probe=True)
    return {"status": result.get("status", "error"), **result}


@router.get("/workflows")
async def workflows() -> dict:
    return {"workflows": list_workflows()}


def _job_metadata(job) -> dict:
    meta = job.input.metadata or {}
    return {key: meta[key] for key in _CORRELATION_KEYS if meta.get(key)}


@router.get("/jobs/{job_id}")
async def job_status(job_id: str) -> dict:
    service = get_image_service()
    job = service.get_job(job_id) or service.get_memory_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "id": job.id,
        "status": job.status.value,
        "error": job.error,
        "provider_job_id": job.provider_job_id,
        "prompt": job.input.prompt,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "metadata": _job_metadata(job),
        "output": job.output.model_dump() if job.output else None,
    }
