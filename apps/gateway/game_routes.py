"""HTTP + WebSocket routes for vision game mode."""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from services.auth.deps import require_operator, resolve_operator_from_token
from services.auth.operator_store import get_db_session
from services.auth.session import OPERATOR_SESSION_COOKIE, verify_operator_session
from services.game import frames as game_frames
from services.game.bridge_manager import bridge_manager
from services.game.deps import check_vigem_available
from services.game.neuro_server import game_hub
from services.game.profiles import list_profiles, load_profile
from services.game.timing import resolve_game_timing
from services.game.trace import read_trace_tail
from services.game.window_detect import list_matching_windows
from services.settings.store import load_effective_settings

log = logging.getLogger("maya-unified.gateway.game")

router = APIRouter(prefix="/api/game", tags=["game"])


class FrameBody(BaseModel):
    image: str = Field(..., min_length=32)
    label: str = ""
    session_id: str | None = None


class ContextBody(BaseModel):
    message: str = Field(..., min_length=1)
    silent: bool = False


class AutonomousStartBody(BaseModel):
    goal: str = Field(..., min_length=1)
    profile_id: str = "pokemon_gba"


class BridgeStartBody(BaseModel):
    profile_id: str = "pokemon_gba"
    goal: str = ""


class GameTimingPatchBody(BaseModel):
    poll_fps: float | None = Field(None, ge=0.5, le=30)
    analysis_fps_min: float | None = Field(None, ge=0.05, le=2)
    analysis_fps_max: float | None = Field(None, ge=0.05, le=2)


async def _resolve_ws_operator(websocket: WebSocket) -> tuple[str | None, Any]:
    token = websocket.cookies.get(OPERATOR_SESSION_COOKIE)
    if not token:
        token = websocket.query_params.get("token")
    payload = verify_operator_session(token or "")
    if not payload:
        return None, None
    async for session in get_db_session():
        op = await resolve_operator_from_token(session, token)
        break
    else:
        op = None
    if op is None or getattr(op, "is_banned", False):
        return None, None
    return str(op.id), op


@router.get("/profiles")
async def get_profiles(_op: Annotated[Any, Depends(require_operator)]):
    return {"ok": True, "profiles": list_profiles()}


@router.get("/profiles/{profile_id}")
async def get_profile(profile_id: str, _op: Annotated[Any, Depends(require_operator)]):
    try:
        p = load_profile(profile_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "ok": True,
        "profile": {
            "id": p.id,
            "display_name": p.display_name,
            "emulator": p.emulator,
            "capture": p.capture,
            "input": p.input,
            "actions": p.neuro_actions(),
            "turn_policy": p.turn_policy,
        },
    }


@router.get("/timing")
async def game_timing(
    op: Annotated[Any, Depends(require_operator)],
    profile_id: str = Query("pokemon_gba"),
):
    try:
        profile = load_profile(profile_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    settings = await asyncio.to_thread(load_effective_settings, str(op.id))
    timing = resolve_game_timing(profile, settings)
    return {
        "ok": True,
        "profile_id": profile.id,
        "timing": timing.to_dict(),
        "settings": settings.get("game") or {},
    }


@router.patch("/timing")
async def patch_game_timing(
    body: GameTimingPatchBody,
    op: Annotated[Any, Depends(require_operator)],
):
    patch: dict[str, Any] = {}
    if body.poll_fps is not None:
        patch["poll_fps"] = body.poll_fps
    if body.analysis_fps_min is not None:
        patch["analysis_fps_min"] = body.analysis_fps_min
    if body.analysis_fps_max is not None:
        patch["analysis_fps_max"] = body.analysis_fps_max
    if not patch:
        return {"ok": False, "error": "no timing fields to update"}

    def _apply_patch() -> dict:
        from services.voice.hub import hub

        return hub.apply_settings_patch({"game": patch}, operator_id=str(op.id))

    merged = await asyncio.to_thread(_apply_patch)
    game_cfg = merged.get("game") or {}
    profile = load_profile("pokemon_gba")
    timing = resolve_game_timing(profile, merged)
    return {"ok": True, "settings": game_cfg, "timing": timing.to_dict()}


@router.get("/status")
async def game_status(
    op: Annotated[Any, Depends(require_operator)],
    session_id: str | None = Query(None),
):
    oid = str(op.id)
    return {
        "ok": True,
        "session": {
            **game_hub.status(oid),
            "bridge": bridge_manager.status(oid),
        },
        "frame": game_frames.status_for(oid, session_id=session_id),
    }


@router.post("/frame")
async def upload_frame(body: FrameBody, op: Annotated[Any, Depends(require_operator)]):
    oid = str(op.id)
    conn = game_hub.get(oid)
    sid = body.session_id or (conn.session_id if conn else "default")
    result = game_frames.put_frame(oid, body.image, session_id=sid, label=body.label)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "frame rejected")
    return {
        "ok": True,
        **result,
        "session_id": sid,
        "frame_ref": game_frames.frame_ref(oid, sid),
    }


@router.get("/windows")
async def game_windows(
    op: Annotated[Any, Depends(require_operator)],
    profile_id: str = Query("pokemon_gba"),
):
    try:
        profile = load_profile(profile_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    title = str(profile.capture.get("title_substring") or profile.emulator or "")
    windows = list_matching_windows(title)
    return {
        "ok": True,
        "profile_id": profile.id,
        "title_substring": title,
        "windows": windows,
        "detected": len(windows) > 0,
    }


@router.get("/bridge/status")
async def bridge_status(op: Annotated[Any, Depends(require_operator)]):
    return {"ok": True, **bridge_manager.status(str(op.id))}


@router.get("/diagnostics")
async def game_diagnostics(
    op: Annotated[Any, Depends(require_operator)],
    profile_id: str = Query("pokemon_gba"),
):
    """Live health snapshot + recent trace events for debugging."""
    oid = str(op.id)
    try:
        profile = load_profile(profile_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    title = str(profile.capture.get("title_substring") or "mGBA")
    windows = list_matching_windows(title)
    capture_ok = False
    capture_hwnd = None
    if sys.platform == "win32":
        try:
            from apps.game_bridge.capture.win32 import Win32Capture

            cap = Win32Capture(title_substring=title)
            b64 = cap.capture_png_base64()
            capture_ok = bool(b64 and len(b64) > 100)
            capture_hwnd = cap._hwnd
        except Exception as exc:  # noqa: BLE001
            capture_ok = False
            capture_hwnd = f"error: {exc}"
    hub_st = game_hub.status(oid)
    bridge_st = bridge_manager.status(oid)
    traces = read_trace_tail(oid, max_lines=30)
    input_info = {
        "backend": profile.input.get("backend", "keyboard"),
        "delivery": profile.input.get("delivery", "postmessage"),
        "note": "Keys go only to mGBA via PostMessage — no focus steal.",
        "vigem_available": check_vigem_available(),
    }
    return {
        "ok": True,
        "operator_id": oid,
        "mgba_windows": windows,
        "capture_ok": capture_ok,
        "capture_hwnd": capture_hwnd,
        "input": input_info,
        "session": hub_st,
        "bridge": bridge_st,
        "trace_tail": traces,
        "trace_file": f"data/game_traces/{oid}.jsonl",
        "bridge_log": f"data/game_bridge_logs/{oid}.log",
    }


@router.post("/force/abort")
async def abort_force(op: Annotated[Any, Depends(require_operator)]):
    return {"ok": True, **game_hub.abort_force(str(op.id), reason="api abort")}


@router.post("/bridge/start")
async def bridge_start(
    request: Request,
    body: BridgeStartBody,
    op: Annotated[Any, Depends(require_operator)],
):
    token = request.cookies.get(OPERATOR_SESSION_COOKIE) or ""
    gateway = str(request.base_url).rstrip("/")
    if body.goal.strip():
        game_hub.start_autonomous(str(op.id), body.goal, profile_id=body.profile_id)
    result = bridge_manager.start(
        str(op.id),
        profile_id=body.profile_id,
        gateway=gateway,
        token=token,
        goal=body.goal,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "bridge start failed")
    return result


@router.post("/bridge/stop")
async def bridge_stop(op: Annotated[Any, Depends(require_operator)]):
    return bridge_manager.stop(str(op.id))


@router.post("/session/stop")
async def stop_session(op: Annotated[Any, Depends(require_operator)]):
    oid = str(op.id)
    bridge_manager.stop(oid)
    game_hub.stop_autonomous(oid)
    await game_hub.detach(oid)
    game_frames.clear_frame(oid)
    return {"ok": True}


@router.post("/autonomous/start")
async def start_autonomous(body: AutonomousStartBody, op: Annotated[Any, Depends(require_operator)]):
    result = game_hub.start_autonomous(
        str(op.id),
        body.goal,
        profile_id=body.profile_id,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "start failed")
    return result


@router.post("/autonomous/stop")
async def stop_autonomous(op: Annotated[Any, Depends(require_operator)]):
    return game_hub.stop_autonomous(str(op.id))


@router.websocket("/neuro")
async def neuro_websocket(websocket: WebSocket):
    operator_id, _op = await _resolve_ws_operator(websocket)
    if not operator_id:
        await websocket.close(code=4401)
        return

    profile_id = websocket.query_params.get("profile") or ""
    await websocket.accept()
    conn = await game_hub.attach(operator_id, websocket, profile_id=profile_id)
    log.info("game neuro ws connected operator=%s session=%s", operator_id, conn.session_id)

    try:
        while True:
            raw = await websocket.receive_text()
            await game_hub.handle_message(operator_id, raw)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        log.warning("game ws error: %s", exc)
    finally:
        await game_hub.detach(operator_id)
        log.info("game neuro ws disconnected operator=%s", operator_id)
