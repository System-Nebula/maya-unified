"""Music play endpoints — demo-safe public surface."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from maya_contracts import PlayResolveRequest, PlayResolveResponse

from maya_gateway.services.ontology_resolve import resolve_with_ontology

router = APIRouter(prefix="/api/music", tags=["music"])


@router.post("/play/resolve", response_model=PlayResolveResponse)
async def play_resolve(req: PlayResolveRequest) -> PlayResolveResponse:
    """Resolve a free-text query to a playable track (ontology → demo catalog)."""
    return await resolve_with_ontology(req)


@router.get("/state/{zone}/stream")
async def state_stream(zone: str) -> StreamingResponse:
    """Server-Sent Events heartbeat for player state.

    v1 emits a periodic ``hello`` ping so the Radio widget can confirm the
    channel is live. Future versions will proxy mpd-bridge state.
    """

    async def event_generator():
        yield f"event: hello\ndata: {json.dumps({'zone': zone})}\n\n"
        while True:
            payload = {
                "zone": zone,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            yield f"event: heartbeat\ndata: {json.dumps(payload)}\n\n"
            await asyncio.sleep(15)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
