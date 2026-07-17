"""VOICE-003: browser mic WebSocket heartbeat helpers."""

from __future__ import annotations

from services.voice.browser_ws import HeartbeatState


def test_heartbeat_sends_after_interval() -> None:
    hb = HeartbeatState(last_seen=100.0, last_ping_sent=100.0)
    assert not hb.should_send_ping(110.0, interval_s=15.0)
    assert hb.should_send_ping(115.0, interval_s=15.0)
    hb.mark_ping_sent(115.0)
    assert not hb.should_send_ping(120.0, interval_s=15.0)


def test_heartbeat_timeout_without_touch() -> None:
    hb = HeartbeatState(last_seen=10.0)
    assert not hb.should_timeout(40.0, timeout_s=45.0)
    assert hb.should_timeout(55.0, timeout_s=45.0)


def test_touch_resets_timeout() -> None:
    hb = HeartbeatState(last_seen=10.0)
    hb.touch(50.0)
    assert not hb.should_timeout(80.0, timeout_s=45.0)
    assert hb.should_timeout(95.0, timeout_s=45.0)
