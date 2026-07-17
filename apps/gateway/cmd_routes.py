"""Gateway routes for cmd_registry discovery and dispatch."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query, Request

from services.auth.deps import require_operator
from services.cmd.bootstrap import ensure_cmds_registered
from services.cmd.chat_bridge import dispatch_cmd_request
from services.cmd.models import CmdSurface

router = APIRouter(prefix="/api/cmds", tags=["cmds"])


@router.get("")
def list_cmds(
    request: Request,
    _op: Annotated[Any, Depends(require_operator)],
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
async def dispatch_cmd_route(
    request: Request,
    operator: Annotated[Any, Depends(require_operator)],
    data: dict = Body(...),
) -> dict:
    payload = data or {}
    text = str(payload.get("text") or "").strip() or None
    cmd_id = str(payload.get("cmd_id") or "").strip() or None
    args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
    surface_raw = str(payload.get("surface") or "discord").strip().lower()
    try:
        surface = CmdSurface(surface_raw)
    except ValueError:
        surface = CmdSurface.DISCORD
    # Identity from the authenticated principal only — ignore payload operator_id.
    operator_id = str(operator.id)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    metadata = {
        **metadata,
        "operator_role": getattr(operator, "role", None) or "operator",
    }
    result = await dispatch_cmd_request(
        text=text,
        cmd_id=cmd_id,
        args=args,
        operator_id=operator_id,
        surface=surface,
        metadata=metadata,
    )
    return {"ok": result.ok, **result.model_dump()}
