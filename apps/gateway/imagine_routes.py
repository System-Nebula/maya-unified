"""Imagine-related gateway routes (arena voting for dashboard chat)."""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request

router = APIRouter(prefix="/api/voice/imagine", tags=["imagine"])


def _operator(request: Request):
    op = getattr(request.state, "operator", None)
    if op is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return op


@router.post("/arena/vote")
async def arena_vote(request: Request, payload: dict = Body(...)) -> dict:
    op = _operator(request)
    battle_id = str(payload.get("battle_id") or "").strip()
    choice = str(payload.get("choice") or "").strip().lower()
    if not battle_id:
        raise HTTPException(status_code=400, detail="battle_id required")
    if choice not in {"a", "b", "tie"}:
        raise HTTPException(status_code=400, detail="choice must be a, b, or tie")

    from services.imagine.arena_vote import submit_arena_vote_async

    display_name = str(getattr(op, "display_name", None) or getattr(op, "username", None) or op.id)
    try:
        return await submit_arena_vote_async(
            battle_id=battle_id,
            choice=choice,
            operator_id=str(op.id),
            display_name=display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
