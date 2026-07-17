"""VOICE-003: browser WebSocket connection registry compare-and-remove."""

from __future__ import annotations

from services.voice import browser_ws


def setup_function() -> None:
    browser_ws._reset_connection_registry_for_tests()


def test_replacement_survives_old_connection_release() -> None:
    closed_a = []
    closed_b = []

    id_a = browser_ws.register_browser_connection("op1", lambda: closed_a.append(1))
    id_b = browser_ws.register_browser_connection("op1", lambda: closed_b.append(1))

    assert id_a != id_b
    assert closed_a == [1], "replacement must close only the old connection"
    assert closed_b == []

    removed = browser_ws.release_browser_connection("op1", id_a)
    assert removed is False
    assert browser_ws.get_browser_connection_id("op1") == id_b
    assert closed_b == [], "old finally must not invoke the replacement close hook"

    removed_b = browser_ws.release_browser_connection("op1", id_b)
    assert removed_b is True
    assert browser_ws.get_browser_connection_id("op1") is None


def test_clear_operator_closes_current_only() -> None:
    closed = []
    cid = browser_ws.register_browser_connection("op2", lambda: closed.append("x"))
    browser_ws.clear_disconnect_hook("op2")
    assert closed == ["x"]
    assert browser_ws.get_browser_connection_id("op2") is None
    # Clearing again is a no-op and must not invent a hook call.
    browser_ws.clear_disconnect_hook("op2")
    assert closed == ["x"]
    assert cid


def test_disconnect_all_closes_exact_connections() -> None:
    closed: list[str] = []
    browser_ws.register_browser_connection("a", lambda: closed.append("a"))
    browser_ws.register_browser_connection("b", lambda: closed.append("b"))
    browser_ws.disconnect_all_browser_ws()
    assert sorted(closed) == ["a", "b"]
    assert browser_ws.get_browser_connection_id("a") is None
    assert browser_ws.get_browser_connection_id("b") is None
