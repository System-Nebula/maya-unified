"""CTX-002: TurnContext carries frozen principal snapshot."""

from __future__ import annotations

import pytest

from services.voice.audience import Audience
from services.voice.turn_context import (
    TurnContext,
    resolve_operator_id,
    stamp_event,
)


def test_turn_context_is_frozen() -> None:
    turn = TurnContext(
        session_id="s1",
        turn_id="t1",
        corr_id="c1",
        operator_id="op-a",
    )
    with pytest.raises(Exception):
        turn.operator_id = "op-b"  # type: ignore[misc]


def test_resolve_operator_id_prefers_turn_over_fallback() -> None:
    turn = TurnContext(
        session_id="s1",
        turn_id="t1",
        corr_id="c1",
        operator_id="op-a",
    )
    assert resolve_operator_id(turn, fallback="op-b") == "op-a"
    assert resolve_operator_id(None, fallback="op-b") == "op-b"
    assert resolve_operator_id(None, fallback=None) is None


def test_stamp_event_includes_operator_and_room() -> None:
    turn = TurnContext(
        session_id="s1",
        turn_id="t1",
        corr_id="c1",
        generation_id=3,
        audience=Audience.operator("op-a"),
        operator_id="op-a",
        room_id=None,
        data_dir="/tmp/op-a",
        personality_id="default",
    )
    out = stamp_event({"type": "ai", "text": "hi"}, turn=turn)
    assert out["operator_id"] == "op-a"
    assert out["session_id"] == "s1"
    assert out["generation_id"] == 3
    assert "data_dir" not in out  # not leaked into events


def test_two_contexts_remain_distinct() -> None:
    a = TurnContext(session_id="s", turn_id="t1", corr_id="c1", operator_id="op-a")
    b = TurnContext(session_id="s", turn_id="t2", corr_id="c2", operator_id="op-b")
    assert a.operator_id != b.operator_id
    assert resolve_operator_id(a, fallback="op-b") == "op-a"
