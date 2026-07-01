"""Music query and acquisition endpoints — search Soulseek, download to SeaweedFS, reference in ontology."""

from __future__ import annotations

from maya_contracts import (
    AcquisitionRequest,
    AcquisitionResult,
    AcquisitionStatus,
    SearchHit,
    SearchQuery,
    SearchResult,
)
from maya_gateway.services.slskd_search import (
    enqueue_download,
    get_downloads,
    search_slskd,
)

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/music/query", tags=["music_query"])


@router.post("/search", response_model=SearchResult)
async def search(query: SearchQuery) -> SearchResult:
    """Run a structured Soulseek search.

    Returns ranked hits with quality scores. Results are ephemeral —
    save interesting hits as AcquisitionRequests.
    """
    try:
        return search_slskd(query)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/download", response_model=AcquisitionResult)
async def download(req: AcquisitionRequest) -> AcquisitionResult:
    """Enqueue a file download on slskd.

    Does NOT wait for completion — returns immediately with an enqueued
    status. Poll GET /api/music/query/status for progress.
    """
    transfer_id = enqueue_download(
        username=req.hit.username,
        filename=req.hit.filename,
        size=req.hit.size,
    )
    if transfer_id is None:
        return AcquisitionResult(
            request=req,
            status=AcquisitionStatus.FAILED,
            error="Failed to enqueue download on slskd",
        )

    return AcquisitionResult(
        request=req,
        status=AcquisitionStatus.ENQUEUED,
        slskd_transfer_id=transfer_id,
        s3_key=req.build_s3_key(),
    )


@router.get("/status", response_model=list[dict])
async def download_status() -> list[dict]:
    """List all current and recent slskd transfers."""
    return get_downloads()


@router.post("/search-and-best", response_model=dict)
async def search_and_best(query: SearchQuery) -> dict:
    """Convenience: search and return the best hit + full results.

    Returns:
        best: best SearchHit (or null)
        total_hits: int
        search_id: str
    """
    result = search_slskd(query)
    best = result.best()
    return {
        "best": best.model_dump() if best else None,
        "total_hits": result.total_hits,
        "search_id": result.search_id,
        "elapsed_seconds": result.elapsed_seconds,
        "hint": f"POST /api/music/query/download with this hit to acquire" if best else "No hits",
    }
