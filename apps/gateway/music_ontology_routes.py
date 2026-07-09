"""Music ontology lookup and set-list indexing HTTP routes."""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from maya_contracts import (
    IndexMusicUrlRequest,
    MusicReactionRequest,
    MusicReactionResponse,
    ResolvedSetModel,
    SetEntryModel,
    TrackMetadata,
)

from services.auth.deps import require_operator
from services.music import ontology as music_ontology

router = APIRouter(prefix="/api/music", tags=["music-ontology"])


def _resolved_to_model(resolved) -> ResolvedSetModel:
    return ResolvedSetModel(
        set_key=resolved.set_key,
        title=resolved.title,
        container_url=resolved.container_url,
        container_schema=resolved.container_schema,
        entries=[
            SetEntryModel(
                position=e.position,
                start_seconds=e.start_seconds,
                end_seconds=e.end_seconds,
                label=e.label,
                artist=e.artist,
                title=e.title,
                work_key=e.work_key,
                play_mode=e.play_mode,
                source_refs=e.source_refs,
            )
            for e in resolved.entries
        ],
        linked_sets=resolved.linked_sets,
        attrs=resolved.attrs,
    )


@router.get("/ontology/lookup", response_model=TrackMetadata)
async def ontology_lookup(
    q: Annotated[str, Query(min_length=1)],
    _op=Depends(require_operator),
) -> TrackMetadata:
    meta = await music_ontology.lookup(q)
    if meta is None:
        raise HTTPException(status_code=404, detail="no confident ontology match")
    return meta


@router.get("/ontology/works/{work_key:path}")
async def ontology_work_detail(
    work_key: str,
    _op=Depends(require_operator),
) -> dict:
    detail = await music_ontology.get_work_detail(work_key)
    if detail is None:
        raise HTTPException(status_code=404, detail="work not found")
    return detail


@router.post("/url/index", response_model=ResolvedSetModel)
async def index_music_url_route(
    req: IndexMusicUrlRequest,
    _op=Depends(require_operator),
) -> ResolvedSetModel:
    from services.music.url_handler import detect_platform, index_music_url

    url = (req.url or "").strip()
    if not url or not detect_platform(url):
        raise HTTPException(status_code=400, detail="unsupported or invalid music URL")
    resolved = await index_music_url(url, correlate=req.correlate, ingest=True)
    if resolved is None:
        raise HTTPException(status_code=404, detail="no tracklist found for URL")
    return _resolved_to_model(resolved)


@router.post("/reactions", response_model=MusicReactionResponse)
async def set_music_reaction(
    req: MusicReactionRequest,
    op=Depends(require_operator),
) -> MusicReactionResponse:
    from services.music.reactions import set_reaction

    try:
        result = await set_reaction(
            operator_id=op.id,
            entity_type=req.entity_type,
            entity_key=req.entity_key,
            reaction=req.reaction,
            source_url=req.source_url,
            attrs=req.attrs,
            active=req.active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MusicReactionResponse(**result)


@router.get("/reactions")
async def list_music_reactions(
    entity_type: Optional[str] = None,
    entity_key: Optional[str] = None,
    op=Depends(require_operator),
) -> list[dict]:
    from services.music.reactions import list_reactions

    return await list_reactions(
        entity_type=entity_type,
        entity_key=entity_key,
        operator_id=op.id,
    )
