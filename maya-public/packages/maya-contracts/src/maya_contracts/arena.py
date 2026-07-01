"""Arena battle contracts."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from maya_contracts.common import StrictModel


class AddCandidateRequest(StrictModel):
    name: str
    provider: str
    voice_id: str
    description: Optional[str] = None
    settings: Optional[dict] = None
    model_release_id: Optional[str] = None


class CreateBattleRequest(StrictModel):
    candidate_a_id: str
    candidate_b_id: str
    prompt: str
    prompt_source: Optional[str] = None


class VoteRequest(StrictModel):
    choice: str  # "a", "b", or "tie"


class CandidateResponse(StrictModel):
    id: str
    model_release_id: Optional[str] = None
    name: str
    provider: str
    voice_id: str
    rating: int
    wins: int
    losses: int
    draws: int
    total_battles: int
    win_rate: float
    description: Optional[str] = None
    is_active: bool = True


class BattleResponse(StrictModel):
    id: str
    candidate_a_id: str
    candidate_b_id: str
    prompt: str
    winner_id: Optional[str] = None
    status: str
    votes_a: int = 0
    votes_b: int = 0
    votes_tie: int = 0
    total_votes: int = 0
    created_at: str
    completed_at: Optional[str] = None


class LeaderboardResponse(StrictModel):
    candidates: list[CandidateResponse]
    total: int


class StatsResponse(StrictModel):
    total_candidates: int
    total_battles: int
    total_votes: int
