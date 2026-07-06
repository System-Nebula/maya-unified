"""Bandcamp integration routes — status and settings probe."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from maya_db.models.operator import OperatorUser

from services.auth.deps import require_operator
from services.integrations.bandcamp import BandcampError, connection_status, resolve_username
from services.settings.store import load_effective_settings
from services.voice.hub import hub

router = APIRouter(tags=["bandcamp-integrations"])


@router.get("/api/integrations/bandcamp/status")
async def bandcamp_integration_status(
    op: Annotated[OperatorUser, Depends(require_operator)],
):
    settings = load_effective_settings(str(op.id))
    username = resolve_username(settings)
    if not username:
        return {
            "connected": False,
            "username": "",
            "wishlist_count": 0,
            "enabled": bool((settings.get("bandcamp") or {}).get("enabled", True)),
        }
    status = connection_status(username)
    status["enabled"] = bool((settings.get("bandcamp") or {}).get("enabled", True))
    return status


@router.post("/api/integrations/bandcamp/username")
async def bandcamp_save_username(
    op: Annotated[OperatorUser, Depends(require_operator)],
    body: dict,
):
    username = str(body.get("username") or "").strip().lstrip("@")
    enabled = body.get("enabled", True)
    patch = {
        "bandcamp": {
            "enabled": bool(enabled),
            "username": username,
        }
    }
    try:
        hub.apply_settings_patch(patch, operator_id=str(op.id))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    settings = load_effective_settings(str(op.id))
    resolved = resolve_username(settings)
    if not resolved:
        return {
            "ok": True,
            "connected": False,
            "username": "",
            "wishlist_count": 0,
        }

    try:
        status = connection_status(resolved)
    except BandcampError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **status}
