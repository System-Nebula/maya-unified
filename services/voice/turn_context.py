"""Captured turn identity for voice events (VOICE-002 / CTX-002)."""

from __future__ import annotations

from dataclasses import dataclass, replace

from services.voice.audience import Audience


@dataclass(frozen=True)
class TurnContext:
    """IDs and principal snapshot captured at turn creation.

    Never re-read hub mutable globals after construction. Heavy shared weights
    (models) may stay process-global; operator/room/settings identity must not.
    """

    session_id: str
    turn_id: str
    corr_id: str
    generation_id: int = 0
    audience: Audience | None = None
    # CTX-002 principal / settings snapshot (optional for back-compat)
    operator_id: str | None = None
    room_id: str | None = None
    data_dir: str | None = None
    personality_id: str | None = None
    settings_fingerprint: str | None = None

    def with_audience(self, audience: Audience | None) -> TurnContext:
        return replace(self, audience=audience)


def resolve_operator_id(
    turn: TurnContext | None,
    *,
    fallback: str | None = None,
) -> str | None:
    """Prefer the frozen turn principal over hub/process fallbacks."""
    if turn is not None and turn.operator_id:
        return str(turn.operator_id)
    fb = str(fallback or "").strip()
    return fb or None


def should_commit_turn(
    ctx: TurnContext,
    *,
    active_session_id: str | None,
    active_turn: TurnContext | None,
    active_generation_id: int | None = None,
) -> bool:
    """Require the exact live session, turn, and generation before persistence."""
    if active_turn is None:
        return False
    if ctx.session_id:
        if not active_session_id or ctx.session_id != active_session_id:
            return False
    elif active_session_id:
        return False
    if active_turn.turn_id != ctx.turn_id or active_turn.session_id != ctx.session_id:
        return False
    generation = active_turn.generation_id if active_generation_id is None else active_generation_id
    return int(ctx.generation_id) == int(generation)


def stamp_event(
    event: dict,
    *,
    session_id: str | None = None,
    turn: TurnContext | None = None,
    sequence: int | None = None,
    audience: Audience | None = None,
) -> dict:
    """Attach envelope fields without overwriting caller-provided values."""
    out = dict(event)
    if turn is not None:
        out.setdefault("session_id", turn.session_id)
        out.setdefault("turn_id", turn.turn_id)
        out.setdefault("corr_id", turn.corr_id)
        out.setdefault("generation_id", turn.generation_id)
        if turn.audience is not None:
            out.setdefault("audience", turn.audience.to_dict())
        if turn.operator_id:
            out.setdefault("operator_id", turn.operator_id)
        if turn.room_id:
            out.setdefault("room_id", turn.room_id)
    elif session_id:
        out.setdefault("session_id", session_id)
    if audience is not None:
        out.setdefault("audience", audience.to_dict())
    if sequence is not None:
        out.setdefault("sequence", sequence)
    return out
