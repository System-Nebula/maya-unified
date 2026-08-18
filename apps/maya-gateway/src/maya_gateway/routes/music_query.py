"""Music query and download endpoints — search Soulseek, download to SeaweedFS, reference in ontology."""

from __future__ import annotations

from maya_contracts import (
    DownloadRequest,
    DownloadResult,
    SearchQuery,
    SearchResult,
)
from maya_gateway.services.slskd_search import (
    get_downloads,
    run_download,
    search_slskd,
)

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/music/query", tags=["music_query"])


def _slskd_unavailable(exc: Exception) -> HTTPException:
    detail = str(exc)
    status = 503 if "SLSKD_API_KEY" in detail else 502
    return HTTPException(status_code=status, detail=detail)


@router.post("/search", response_model=SearchResult)
async def search(query: SearchQuery) -> SearchResult:
    """Run a structured Soulseek search.

    Returns ranked hits with quality scores. Results are ephemeral —
    save interesting hits as DownloadRequests.
    """
    try:
        return search_slskd(query)
    except Exception as exc:
        raise _slskd_unavailable(exc) from exc


@router.post("/download", response_model=DownloadResult)
async def download(req: DownloadRequest) -> DownloadResult:
    """Enqueue a file download on slskd.

    ``wait_seconds`` defaults to 0 so the HTTP call returns immediately with
    an enqueued status. Pass a positive wait to poll until complete and
    verify transferred size (and on-disk size when the file is present).
    """
    try:
        return run_download(req)
    except Exception as exc:
        raise _slskd_unavailable(exc) from exc


@router.get("/status", response_model=list[dict])
async def download_status() -> list[dict]:
    """List all current and recent slskd transfers."""
    try:
        return get_downloads()
    except Exception as exc:
        raise _slskd_unavailable(exc) from exc


@router.post("/search-and-best", response_model=dict)
async def search_and_best(query: SearchQuery) -> dict:
    """Convenience: search and return the best hit + full results.

    Returns:
        best: best SearchHit (or null)
        total_hits: int
        search_id: str
    """
    try:
        result = search_slskd(query)
    except Exception as exc:
        raise _slskd_unavailable(exc) from exc
    best = result.best()
    return {
        "best": best.model_dump() if best else None,
        "total_hits": result.total_hits,
        "search_id": result.search_id,
        "elapsed_seconds": result.elapsed_seconds,
        "hint": "POST /api/music/query/download with this hit to download" if best else "No hits",
    }
