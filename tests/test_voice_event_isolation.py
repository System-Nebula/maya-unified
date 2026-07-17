"""SEC-004 regressions for exact SSE audience isolation."""

from __future__ import annotations

from services.voice.audience import Audience
from services.voice.hub import VoiceHub


def _drain(queue) -> list[dict]:
    events: list[dict] = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


def _subscribers() -> tuple[VoiceHub, object, object, object, object]:
    hub = VoiceHub()
    op_a = hub.subscribe(operator_id="op-a")
    op_b = hub.subscribe(operator_id="op-b")
    room_x = hub.subscribe(room_id="room-x")
    room_y = hub.subscribe(room_id="room-y")
    for q in (op_a, op_b, room_x, room_y):
        _drain(q)
    return hub, op_a, op_b, room_x, room_y


def test_operator_audio_reaches_only_that_operator() -> None:
    hub, op_a, op_b, room_x, room_y = _subscribers()

    hub.broadcast(
        {"type": "audio", "format": "f32le", "data": "private"},
        operator_id="op-a",
    )

    assert [e["data"] for e in _drain(op_a) if e.get("type") == "audio"] == [
        "private"
    ]
    assert not _drain(op_b)
    assert not _drain(room_x)
    assert not _drain(room_y)


def test_operator_status_and_error_do_not_leak() -> None:
    hub, op_a, op_b, room_x, _room_y = _subscribers()

    hub.broadcast({"type": "status", "value": "thinking"}, operator_id="op-a")
    hub.broadcast({"type": "error", "text": "private failure"}, operator_id="op-a")

    assert [event["type"] for event in _drain(op_a)] == ["status", "error"]
    assert not _drain(op_b)
    assert not _drain(room_x)


def test_room_event_reaches_only_exact_room() -> None:
    hub, op_a, op_b, room_x, room_y = _subscribers()

    hub.broadcast({"type": "ai", "text": "room private"}, room_id="room-x")

    assert [event.get("text") for event in _drain(room_x)] == ["room private"]
    assert not _drain(room_y)
    assert not _drain(op_a)
    assert not _drain(op_b)


def test_captured_audience_routes_without_mutable_hub_context() -> None:
    hub, op_a, op_b, room_x, _room_y = _subscribers()

    hub.broadcast(
        {
            "type": "ai",
            "text": "captured",
            "audience": Audience.operator("op-a").to_dict(),
        }
    )

    assert [event.get("text") for event in _drain(op_a)] == ["captured"]
    assert not _drain(op_b)
    assert not _drain(room_x)


def test_global_readiness_is_explicitly_delivered_to_all() -> None:
    hub, op_a, op_b, room_x, room_y = _subscribers()

    hub.broadcast(
        {
            "type": "ready",
            "value": True,
            "audience": Audience.global_().to_dict(),
        }
    )

    for q in (op_a, op_b, room_x, room_y):
        assert [event.get("type") for event in _drain(q)] == ["ready"]


def test_invalid_explicit_audience_fails_closed() -> None:
    hub, op_a, op_b, room_x, room_y = _subscribers()

    hub.broadcast(
        {
            "type": "audio",
            "data": "must-drop",
            "audience": {"kind": "operator", "id": ""},
        }
    )

    for q in (op_a, op_b, room_x, room_y):
        assert not _drain(q)
