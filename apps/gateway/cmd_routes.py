"""Gateway routes for cmd_registry discovery and dispatch."""

from __future__ import annotations

from fastapi import APIRouter, Body, Query, Request

from services.cmd.bootstrap import ensure_cmds_registered
from services.cmd.chat_bridge import dispatch_cmd_request
from services.cmd.models import CmdSurface

router = APIRouter(prefix="/api/cmds", tags=["cmds"])


def _operator_id(request: Request) -> str:
    op = getattr(request.state, "operator", None)
    return str(op.id) if op else ""


@router.get("")
def list_cmds(
    request: Request,
    surface: str | None = Query(default=None),
) -> dict:
    ensure_cmds_registered()
    from services.cmd.registry import registry

    surf = None
    if surface:
        try:
            surf = CmdSurface(surface.strip().lower())
        except ValueError:
            surf = None
    return {"ok": True, "cmds": registry.discovery(surface=surf)}


@router.post("/dispatch")
async def dispatch_cmd_route(request: Request, data: dict = Body(...)) -> dict:
    payload = data or {}
    text = str(payload.get("text") or "").strip() or None
    cmd_id = str(payload.get("cmd_id") or "").strip() or None
    args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
    surface_raw = str(payload.get("surface") or "discord").strip().lower()
    try:
        surface = CmdSurface(surface_raw)
    except ValueError:
        surface = CmdSurface.DISCORD
    operator_id = str(payload.get("operator_id") or _operator_id(request) or "").strip() or None
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    result = await dispatch_cmd_request(
        text=text,
        cmd_id=cmd_id,
        args=args,
        operator_id=operator_id,
        surface=surface,
        metadata=metadata,
    )
    return {"ok": result.ok, **result.model_dump()}
