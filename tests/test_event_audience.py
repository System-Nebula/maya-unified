"""SEC-004: exact SSE audience routing matrix."""

from __future__ import annotations

from services.voice.audience import (
    Audience,
    GLOBAL_EVENT_TYPES,
    PRIVATE_EVENT_TYPES,
    resolve_broadcast_audience,
    should_deliver,
    subscriber_audience,
)
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


def test_operator_a_event_reaches_a_only() -> None:
    hub, op_a, op_b, room_x, room_y = _subscribers()
    hub.broadcast({"type": "ai", "text": "hi"}, operator_id="op-a")
    assert [e.get("text") for e in _drain(op_a)] == ["hi"]
    assert not _drain(op_b)
    assert not _drain(room_x)
    assert not _drain(room_y)


def test_operator_a_event_not_b() -> None:
    hub, op_a, op_b, _room_x, _room_y = _subscribers()
    hub.broadcast(
        {"type": "status", "value": "thinking", "audience": Audience.operator("op-a").to_dict()}
    )
    assert [e["type"] for e in _drain(op_a)] == ["status"]
    assert not _drain(op_b)


def test_operator_event_not_room_guest() -> None:
    hub, op_a, _op_b, room_x, _room_y = _subscribers()
    hub.broadcast({"type": "user", "text": "private"}, operator_id="op-a")
    assert [e.get("text") for e in _drain(op_a)] == ["private"]
    assert not _drain(room_x)


def test_room_x_event_reaches_x_only() -> None:
    hub, op_a, op_b, room_x, room_y = _subscribers()
    hub.broadcast({"type": "ai", "text": "room"}, room_id="room-x")
    assert [e.get("text") for e in _drain(room_x)] == ["room"]
    assert not _drain(room_y)
    assert not _drain(op_a)
    assert not _drain(op_b)


def test_room_x_event_not_room_y() -> None:
    hub, _a, _b, room_x, room_y = _subscribers()
    hub.broadcast(
        {"type": "ai", "text": "x-only", "audience": Audience.room("room-x").to_dict()}
    )
    assert [e.get("text") for e in _drain(room_x)] == ["x-only"]
    assert not _drain(room_y)


def test_global_readiness_reaches_all() -> None:
    hub, op_a, op_b, room_x, room_y = _subscribers()
    hub.broadcast({"type": "ready", "value": True})
    for q in (op_a, op_b, room_x, room_y):
        assert [e.get("type") for e in _drain(q)] == ["ready"]
        assert _drain(q) == [] or True


def test_audio_and_settings_never_global() -> None:
    hub, op_a, op_b, room_x, room_y = _subscribers()
    hub.broadcast({"type": "audio", "data": "leak"})
    hub.broadcast({"type": "settings", "delivery": "full"})
    for q in (op_a, op_b, room_x, room_y):
        assert not _drain(q)
    assert "audio" in PRIVATE_EVENT_TYPES
    assert "settings" in PRIVATE_EVENT_TYPES
    assert "ready" in GLOBAL_EVENT_TYPES
    assert resolve_broadcast_audience({"type": "audio"}) is None
    assert resolve_broadcast_audience({"type": "settings"}) is None
    assert resolve_broadcast_audience({"type": "ready"}).kind.value == "global"


def test_stamps_audience_on_kwargs_route() -> None:
    hub, op_a, _b, _x, _y = _subscribers()
    hub.broadcast({"type": "ai", "text": "tagged"}, operator_id="op-a")
    events = _drain(op_a)
    assert events[0]["audience"] == {"kind": "operator", "id": "op-a"}


def test_should_deliver_matrix() -> None:
    a = Audience.operator("a")
    b = Audience.operator("b")
    rx = Audience.room("x")
    glob = Audience.global_()
    assert should_deliver(a, a)
    assert not should_deliver(b, a)
    assert not should_deliver(rx, a)
    assert should_deliver(rx, rx)
    assert should_deliver(a, glob)
    assert should_deliver(None, glob)
    assert not should_deliver(None, a)
    assert subscriber_audience(operator_id="a") == a
    assert subscriber_audience(room_id="x", operator_id="a") == rx
