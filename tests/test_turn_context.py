"""VOICE-002: session/turn/generation/audience envelope and stale-turn commit gating."""

from __future__ import annotations

from services.voice.audience import Audience, AudienceKind, audience_matches
from services.voice.turn_context import TurnContext, should_commit_turn, stamp_event


def test_stamp_event_fills_captured_turn_fields() -> None:
    turn = TurnContext(
        session_id="s_abc",
        turn_id="t_def",
        corr_id="c_ghi",
        generation_id=7,
        audience=Audience.operator("op_1"),
    )
    ev = stamp_event({"type": "status", "value": "thinking"}, turn=turn, sequence=3)
    assert ev == {
        "type": "status",
        "value": "thinking",
        "session_id": "s_abc",
        "turn_id": "t_def",
        "corr_id": "c_ghi",
        "generation_id": 7,
        "audience": {"kind": "operator", "id": "op_1"},
        "sequence": 3,
    }


def test_stamp_event_does_not_overwrite_explicit_ids() -> None:
    turn = TurnContext(session_id="s_1", turn_id="t_1", corr_id="c_1", generation_id=1)
    ev = stamp_event(
        {"type": "ai", "corr_id": "c_explicit", "text": "hi"},
        turn=turn,
    )
    assert ev["corr_id"] == "c_explicit"
    assert ev["turn_id"] == "t_1"


def test_should_commit_rejects_foreign_session() -> None:
    ctx = TurnContext(session_id="s_old", turn_id="t_1", corr_id="c_1", generation_id=1)
    assert not should_commit_turn(
        ctx, active_session_id="s_new", active_turn=ctx, active_generation_id=1
    )


def test_should_commit_rejects_superseded_turn() -> None:
    old = TurnContext(session_id="s_1", turn_id="t_old", corr_id="c_old", generation_id=1)
    new = TurnContext(session_id="s_1", turn_id="t_new", corr_id="c_new", generation_id=3)
    assert not should_commit_turn(
        old, active_session_id="s_1", active_turn=new, active_generation_id=3
    )


def test_should_commit_allows_matching_turn() -> None:
    ctx = TurnContext(session_id="s_1", turn_id="t_1", corr_id="c_1", generation_id=2)
    assert should_commit_turn(
        ctx, active_session_id="s_1", active_turn=ctx, active_generation_id=2
    )


def test_should_commit_rejects_stopped_session() -> None:
    ctx = TurnContext(session_id="s_1", turn_id="t_1", corr_id="c_1", generation_id=2)
    assert not should_commit_turn(
        ctx, active_session_id=None, active_turn=None, active_generation_id=3
    )


def test_should_commit_rejects_advanced_generation() -> None:
    ctx = TurnContext(session_id="s_1", turn_id="t_1", corr_id="c_1", generation_id=2)
    assert not should_commit_turn(
        ctx, active_session_id="s_1", active_turn=ctx, active_generation_id=3
    )


def test_stamp_preserves_player_captured_turn_against_newer_mutable_context() -> None:
    """Delayed audio already labeled at creation must not pick up a newer turn_id."""
    newer = TurnContext(
        session_id="s_2",
        turn_id="t_2",
        corr_id="c_2",
        generation_id=9,
        audience=Audience.operator("op_new"),
    )
    delayed = {
        "type": "audio",
        "session_id": "s_1",
        "turn_id": "t_1",
        "corr_id": "c_1",
        "generation_id": 3,
        "audience": {"kind": "operator", "id": "op_old"},
        "data": "x",
    }
    out = stamp_event(delayed, turn=newer, sequence=12)
    assert out["session_id"] == "s_1"
    assert out["turn_id"] == "t_1"
    assert out["corr_id"] == "c_1"
    assert out["generation_id"] == 3
    assert out["audience"] == {"kind": "operator", "id": "op_old"}
    assert out["sequence"] == 12


def test_audience_exact_match_matrix() -> None:
    a = Audience.operator("a")
    b = Audience.operator("b")
    room_x = Audience.room("x")
    room_y = Audience.room("y")
    glob = Audience.global_()
    assert audience_matches(a, a)
    assert not audience_matches(b, a)
    assert not audience_matches(room_x, a)
    assert audience_matches(room_x, room_x)
    assert not audience_matches(room_y, room_x)
    assert audience_matches(a, glob)
    assert audience_matches(room_x, glob)


def test_audience_construction_rules() -> None:
    assert Audience.global_().kind is AudienceKind.GLOBAL
    try:
        Audience(kind=AudienceKind.GLOBAL, id="nope")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    try:
        Audience(kind=AudienceKind.OPERATOR, id=None)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
