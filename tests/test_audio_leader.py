"""VOICE-005: SSE audio fanout only to claimed leader subscriber."""

from __future__ import annotations

from services.voice.hub import VoiceHub


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _take_hello(q) -> str:
    hello = q.get_nowait()
    assert hello["type"] == "sse_hello"
    while not q.empty():
        q.get_nowait()
    return hello["subscriber_id"]


def test_leader_receives_audio_observer_receives_text_only() -> None:
    hub = VoiceHub()
    q_leader = hub.subscribe(operator_id="op1")
    q_observer = hub.subscribe(operator_id="op1")

    leader_id = _take_hello(q_leader)
    _take_hello(q_observer)
    hub.claim_audio_leader("op1", leader_id, leader=True)

    hub.broadcast({"type": "audio", "format": "f32le", "data": "x"}, operator_id="op1")
    hub.broadcast({"type": "ai", "text": "hello"}, operator_id="op1")

    leader_events = _drain(q_leader)
    observer_events = _drain(q_observer)

    assert any(e.get("type") == "audio" for e in leader_events)
    assert not any(e.get("type") == "audio" for e in observer_events)
    assert any(e.get("type") == "ai" for e in leader_events)
    assert any(e.get("type") == "ai" for e in observer_events)


def test_unsubscribe_clears_leader_claim() -> None:
    hub = VoiceHub()
    q = hub.subscribe(operator_id="op1")
    hello = q.get_nowait()
    sid = hello["subscriber_id"]
    hub.claim_audio_leader("op1", sid, leader=True)
    assert hub._audio_leader_by_operator.get("op1") == sid  # noqa: SLF001
    hub.unsubscribe(q)
    assert "op1" not in hub._audio_leader_by_operator  # noqa: SLF001


def test_without_claim_all_tabs_still_get_audio() -> None:
    """Backward compatible until a leader claims."""
    hub = VoiceHub()
    q_a = hub.subscribe(operator_id="op1")
    q_b = hub.subscribe(operator_id="op1")
    _take_hello(q_a)
    _take_hello(q_b)
    hub.broadcast({"type": "audio", "data": "x"}, operator_id="op1")
    assert any(e.get("type") == "audio" for e in _drain(q_a))
    assert any(e.get("type") == "audio" for e in _drain(q_b))
