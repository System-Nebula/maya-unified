"""Chat arena vote handler — record vote, complete battle, reveal models."""

from __future__ import annotations

import asyncio
from typing import Any


def _winner_slot(battle) -> str | None:
    if battle.votes_a > battle.votes_b and battle.votes_a > battle.votes_tie:
        return "a"
    if battle.votes_b > battle.votes_a and battle.votes_b > battle.votes_tie:
        return "b"
    if battle.votes_tie > battle.votes_a and battle.votes_tie > battle.votes_b:
        return "tie"
    return None


def submit_arena_vote(
    *,
    battle_id: str,
    choice: str,
    operator_id: str,
    display_name: str,
) -> dict[str, Any]:
    from maya_image.arena.service import get_arena_service
    from maya_image.workflows import apply_workflow_elo_from_vote

    normalized = str(choice or "").strip().lower()
    if normalized not in {"a", "b", "tie"}:
        raise ValueError("choice must be a, b, or tie")

    arena = get_arena_service()
    battle = arena.get_battle(battle_id)
    if battle is None:
        raise ValueError("Battle not found")
    if battle.status != "voting":
        raise ValueError("Battle is not open for voting")

    arena.vote(battle_id, operator_id, display_name, normalized)
    if normalized in {"a", "b"}:
        arena.record_sentiment(
            battle_id,
            normalized,
            operator_id,
            display_name,
            "up",
        )
        arena.apply_sentiment_elo(battle_id, normalized, "up")

    completed = arena.complete_battle(battle_id)
    battle_input = completed.input_payload or {}
    if normalized in {"a", "b"}:
        apply_workflow_elo_from_vote(battle_input, normalized)

    candidate_a = arena.get_candidate(completed.candidate_a_id)
    candidate_b = arena.get_candidate(completed.candidate_b_id)
    model_a = candidate_a.name if candidate_a else "A"
    model_b = candidate_b.name if candidate_b else "B"
    winner = _winner_slot(completed)

    return {
        "ok": True,
        "choice": normalized,
        "winner": winner,
        "state": "resolved",
        "model_a": model_a,
        "model_b": model_b,
        "rating_a": candidate_a.rating if candidate_a else None,
        "rating_b": candidate_b.rating if candidate_b else None,
        "battle_id": battle_id,
    }


async def submit_arena_vote_async(
    *,
    battle_id: str,
    choice: str,
    operator_id: str,
    display_name: str,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        submit_arena_vote,
        battle_id=battle_id,
        choice=choice,
        operator_id=operator_id,
        display_name=display_name,
    )
