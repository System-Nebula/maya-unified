"""SEC-005: WebLLM ownership and fulfillment scoping."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from services.llm import webllm_broker
from services.voice.audience import Audience, should_deliver, subscriber_audience


@pytest.fixture(autouse=True)
def _reset_broker():
    webllm_broker._reset_for_tests()
    webllm_broker.set_broadcast(lambda *_a, **_k: None)
    yield
    webllm_broker._reset_for_tests()


def test_operator_b_cannot_fulfill_operator_a_request() -> None:
    events: list[dict] = []

    def capture(event, **kwargs):
        events.append(event)

    webllm_broker.set_broadcast(capture)
    webllm_broker.mark_browser_ready("op-a", "conn-a", True)

    def _consume():
        list(
            webllm_broker.request_stream(
                [{"role": "user", "content": "hi"}],
                operator_id="op-a",
                connection_id="conn-a",
                timeout=2.0,
            )
        )

    t = threading.Thread(target=_consume, daemon=True)
    t.start()
    for _ in range(50):
        snap = webllm_broker.pending_snapshot_for_tests()
        if snap:
            break
        threading.Event().wait(0.02)
    assert snap
    request_id = next(iter(snap))

    assert (
        webllm_broker.fulfill(
            request_id,
            operator_id="op-b",
            connection_id="conn-a",
            chunk="stolen",
            done=True,
        )
        is False
    )
    assert (
        webllm_broker.fulfill(
            request_id,
            operator_id="op-a",
            connection_id="conn-other",
            chunk="stolen",
            done=True,
        )
        is False
    )
    assert (
        webllm_broker.fulfill(
            request_id,
            operator_id="op-a",
            connection_id="conn-a",
            chunk="ok",
            done=True,
        )
        is True
    )
    t.join(timeout=3)
    assert events
    assert events[0]["type"] == "webllm_request"
    assert events[0]["audience"]["id"] == "op-a"
    assert events[0]["connection_id"] == "conn-a"


def test_room_guest_cannot_see_operator_webllm_prompt() -> None:
    event = {
        "type": "webllm_request",
        "id": "r1",
        "messages": [{"role": "user", "content": "secret"}],
        "audience": Audience.operator("op-a").to_dict(),
    }
    room_sub = subscriber_audience(room_id="room-1")
    assert should_deliver(room_sub, Audience.operator("op-a")) is False
    op_sub = subscriber_audience(operator_id="op-a")
    assert should_deliver(op_sub, Audience.from_dict(event["audience"])) is True


def test_old_generation_fulfillment_is_rejected() -> None:
    webllm_broker.mark_browser_ready("op-a", "conn-a", True)
    done = threading.Event()
    err: list[BaseException] = []

    def _consume():
        try:
            list(
                webllm_broker.request_stream(
                    [{"role": "user", "content": "hi"}],
                    operator_id="op-a",
                    connection_id="conn-a",
                    generation_id=1,
                    timeout=2.0,
                )
            )
        except BaseException as exc:  # noqa: BLE001
            err.append(exc)
        finally:
            done.set()

    t = threading.Thread(target=_consume, daemon=True)
    t.start()
    for _ in range(50):
        snap = webllm_broker.pending_snapshot_for_tests()
        if snap:
            break
        threading.Event().wait(0.02)
    request_id = next(iter(snap))
    assert (
        webllm_broker.fulfill(
            request_id,
            operator_id="op-a",
            connection_id="conn-a",
            chunk="late",
            done=True,
            generation_id=2,
        )
        is False
    )
    assert (
        webllm_broker.fulfill(
            request_id,
            operator_id="op-a",
            connection_id="conn-a",
            chunk="ok",
            done=True,
            generation_id=1,
        )
        is True
    )
    done.wait(timeout=3)
    t.join(timeout=1)


def test_disconnect_cancels_pending_requests() -> None:
    webllm_broker.mark_browser_ready("op-a", "conn-a", True)
    errors: list[BaseException] = []

    def _consume():
        try:
            list(
                webllm_broker.request_stream(
                    [{"role": "user", "content": "hi"}],
                    operator_id="op-a",
                    connection_id="conn-a",
                    timeout=3.0,
                )
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t = threading.Thread(target=_consume, daemon=True)
    t.start()
    for _ in range(50):
        if webllm_broker.pending_snapshot_for_tests():
            break
        threading.Event().wait(0.02)
    webllm_broker.mark_browser_ready("op-a", "conn-a", False)
    t.join(timeout=3)
    assert errors
    assert "disconnect" in str(errors[0]).lower() or "WebLLM" in str(errors[0])


def test_duplicate_fulfillment_is_rejected() -> None:
    webllm_broker.mark_browser_ready("op-a", "conn-a", True)

    def _consume():
        list(
            webllm_broker.request_stream(
                [{"role": "user", "content": "hi"}],
                operator_id="op-a",
                connection_id="conn-a",
                timeout=2.0,
            )
        )

    t = threading.Thread(target=_consume, daemon=True)
    t.start()
    for _ in range(50):
        snap = webllm_broker.pending_snapshot_for_tests()
        if snap:
            break
        threading.Event().wait(0.02)
    request_id = next(iter(snap))
    assert webllm_broker.fulfill(
        request_id, operator_id="op-a", connection_id="conn-a", done=True
    )
    assert (
        webllm_broker.fulfill(
            request_id, operator_id="op-a", connection_id="conn-a", chunk="again", done=True
        )
        is False
    )
    t.join(timeout=3)
