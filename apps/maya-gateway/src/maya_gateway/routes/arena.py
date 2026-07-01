"""Arena battle endpoints — backed by Postgres."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from maya_contracts import (
    AddCandidateRequest,
    BattleResponse,
    CandidateResponse,
    CreateBattleRequest,
    LeaderboardResponse,
    StatsResponse,
    VoteRequest,
)
from maya_db import Candidate, Battle, get_async_session
from sqlalchemy import func, select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/arena", tags=["arena"])


def _candidate_to_response(c: Candidate) -> CandidateResponse:
    return CandidateResponse(
        id=str(c.id),
        model_release_id=c.model_release_id,
        name=c.name,
        provider=c.provider,
        voice_id=c.voice_id,
        rating=c.rating,
        wins=c.wins,
        losses=c.losses,
        draws=c.draws,
        total_battles=c.total_battles,
        win_rate=c.win_rate,
        description=c.description,
        is_active=c.is_active,
    )


def _battle_to_response(b: Battle) -> BattleResponse:
    return BattleResponse(
        id=str(b.id),
        candidate_a_id=b.candidate_a_id,
        candidate_b_id=b.candidate_b_id,
        prompt=b.prompt,
        winner_id=b.winner_id,
        status=b.status,
        votes_a=b.votes_a,
        votes_b=b.votes_b,
        votes_tie=b.votes_tie,
        total_votes=b.total_votes,
        created_at=b.created_at.isoformat(),
        completed_at=b.completed_at.isoformat() if b.completed_at else None,
    )


@router.post("/candidates", response_model=CandidateResponse)
async def add_candidate(
    req: AddCandidateRequest,
    session: AsyncSession = Depends(get_async_session),
):
    candidate = Candidate(
        name=req.name,
        provider=req.provider,
        voice_id=req.voice_id,
        description=req.description,
        settings=str(req.settings) if req.settings else None,
        model_release_id=req.model_release_id,
    )
    session.add(candidate)
    await session.flush()
    return _candidate_to_response(candidate)


@router.get("/candidates", response_model=LeaderboardResponse)
async def list_candidates(
    session: AsyncSession = Depends(get_async_session),
):
    result = await session.execute(
        select(Candidate).order_by(Candidate.rating.desc())
    )
    items = [_candidate_to_response(c) for c in result.scalars().all()]
    return LeaderboardResponse(candidates=items, total=len(items))


@router.post("/battles", response_model=BattleResponse)
async def create_battle(
    req: CreateBattleRequest,
    session: AsyncSession = Depends(get_async_session),
):
    a = await session.get(Candidate, req.candidate_a_id)
    b = await session.get(Candidate, req.candidate_b_id)
    if not a:
        raise HTTPException(status_code=404, detail="candidate_a not found")
    if not b:
        raise HTTPException(status_code=404, detail="candidate_b not found")

    battle = Battle(
        candidate_a_id=req.candidate_a_id,
        candidate_b_id=req.candidate_b_id,
        prompt=req.prompt,
        prompt_source=req.prompt_source,
        status="open",
        created_at=datetime.now(timezone.utc),
    )
    session.add(battle)
    await session.flush()
    return _battle_to_response(battle)


@router.post("/battles/{battle_id}/vote", response_model=BattleResponse)
async def vote(
    battle_id: str,
    req: VoteRequest,
    session: AsyncSession = Depends(get_async_session),
):
    from arena_core import ELOCalculator

    battle = await session.get(Battle, battle_id)
    if not battle:
        raise HTTPException(status_code=404, detail="battle not found")
    if battle.status != "open":
        raise HTTPException(status_code=400, detail="battle is closed")

    if req.choice == "a":
        battle.votes_a += 1
    elif req.choice == "b":
        battle.votes_b += 1
    elif req.choice == "tie":
        battle.votes_tie += 1
    else:
        raise HTTPException(status_code=400, detail="choice must be a, b, or tie")

    battle.total_votes += 1

    # Auto-close at 10 votes for demo
    if battle.total_votes >= 10:
        a = await session.get(Candidate, battle.candidate_a_id)
        b = await session.get(Candidate, battle.candidate_b_id)
        assert a and b

        if battle.votes_a > battle.votes_b:
            winner = "a"
        elif battle.votes_b > battle.votes_a:
            winner = "b"
        else:
            winner = "tie"

        result = ELOCalculator.calculate_from_battle(
            a.rating, b.rating, winner, is_tie=(winner == "tie")
        )

        a.rating = result[0][0]
        b.rating = result[1][0]

        if winner == "a":
            a.wins += 1
            b.losses += 1
            battle.winner_id = str(a.id)
        elif winner == "b":
            b.wins += 1
            a.losses += 1
            battle.winner_id = str(b.id)
        else:
            a.draws += 1
            b.draws += 1

        a.total_battles += 1
        b.total_battles += 1
        a.win_rate = a.wins / max(a.total_battles, 1)
        b.win_rate = b.wins / max(b.total_battles, 1)
        battle.status = "completed"
        battle.completed_at = datetime.now(timezone.utc)

    return _battle_to_response(battle)


@router.get("/stats", response_model=StatsResponse)
async def stats(
    session: AsyncSession = Depends(get_async_session),
):
    total_candidates = await session.scalar(select(func.count(Candidate.id)))
    total_battles = await session.scalar(select(func.count(Battle.id)))
    total_votes = await session.scalar(
        select(func.sum(Battle.total_votes))
    ) or 0
    return StatsResponse(
        total_candidates=total_candidates,
        total_battles=total_battles,
        total_votes=total_votes,
    )
