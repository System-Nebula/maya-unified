"""Music ontology lookup HTTP routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from maya_contracts import TrackMetadata

from services.auth.deps import require_operator
from services.music import ontology as music_ontology

router = APIRouter(prefix="/api/music/ontology", tags=["music-ontology"])


@router.get("/lookup", response_model=TrackMetadata)
async def ontology_lookup(
    q: Annotated[str, Query(min_length=1)],
    _op=Depends(require_operator),
) -> TrackMetadata:
    meta = await music_ontology.lookup(q)
    if meta is None:
        raise HTTPException(status_code=404, detail="no confident ontology match")
    return meta


@router.get("/works/{work_key:path}")
async def ontology_work_detail(
    work_key: str,
    _op=Depends(require_operator),
) -> dict:
    detail = await music_ontology.get_work_detail(work_key)
    if detail is None:
        raise HTTPException(status_code=404, detail="work not found")
    return detail
