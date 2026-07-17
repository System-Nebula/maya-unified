"""VOICE-004: bounded SSE subscriber queues."""

from __future__ import annotations

import queue

from services.voice.hub import SSE_QUEUE_MAX, VoiceHub, _Subscriber


def test_sse_audio_marks_slow_consumer_instead_of_unbounded_growth() -> None:
    hub = VoiceHub()
    q: queue.Queue = queue.Queue(maxsize=2)
    sub = _Subscriber(q=q, operator_id="op1")
    hub._scoped_subscribers = [sub]  # noqa: SLF001

    hub._put_subscriber_event(sub, {"type": "status", "value": "listening"})  # noqa: SLF001
    hub._put_subscriber_event(sub, {"type": "status", "value": "thinking"})  # noqa: SLF001
    # Full — control event drops oldest.
    hub._put_subscriber_event(sub, {"type": "status", "value": "speaking"})  # noqa: SLF001
    assert sub.slow is False
    # Audio on a full queue marks the subscriber slow.
    hub._put_subscriber_event(sub, {"type": "audio", "data": "x"})  # noqa: SLF001
    assert sub.slow is True
    assert hub._sse_slow_disconnects >= 1  # noqa: SLF001
    before = q.qsize()
    hub._put_subscriber_event(sub, {"type": "audio", "data": "y"})  # noqa: SLF001
    assert q.qsize() == before
    # Control / tool events still deliver after audio disconnect (may drop oldest).
    hub._put_subscriber_event(sub, {"type": "tool_start", "tool": "web_search"})  # noqa: SLF001
    hub._put_subscriber_event(sub, {"type": "ai", "text": "done", "final": True})  # noqa: SLF001
    items = list(q.queue)
    assert any(e.get("type") == "tool_start" for e in items)
    assert any(e.get("type") == "ai" for e in items)
    # Further audio stays suppressed.
    size_after = q.qsize()
    hub._put_subscriber_event(sub, {"type": "audio", "data": "z"})  # noqa: SLF001
    assert q.qsize() == size_after


def test_subscribe_uses_bounded_queue() -> None:
    hub = VoiceHub()
    q = hub.subscribe(operator_id=None)
    assert q.maxsize == SSE_QUEUE_MAX
