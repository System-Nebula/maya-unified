"""Coordinate in-browser WebLLM inference for server-side voice turns."""

from __future__ import annotations

import queue
import threading
import uuid
from collections.abc import Iterator
from typing import Any, Callable

_BROADCAST: Callable[[dict], None] | None = None
_BROWSER_READY = threading.Event()
_PENDING: dict[str, queue.Queue[Any]] = {}
_LOCK = threading.Lock()
DEFAULT_TIMEOUT = 180.0


def set_broadcast(fn: Callable[[dict], None]) -> None:
    global _BROADCAST
    _BROADCAST = fn


def mark_browser_ready(ready: bool = True) -> None:
    if ready:
        _BROWSER_READY.set()
    else:
        _BROWSER_READY.clear()
        cancel_pending("WebLLM unloaded")


def request_browser_unload() -> None:
    """Tell all dashboard tabs to drop the in-browser model and free WebGPU memory."""
    mark_browser_ready(False)
    _emit({"type": "webllm_unload"})


def cancel_pending(reason: str = "WebLLM bridge reset") -> None:
    """Fail any in-flight browser inference requests."""
    with _LOCK:
        pending = list(_PENDING.items())
        _PENDING.clear()
    err = RuntimeError(reason)
    for _request_id, q in pending:
        try:
            q.put(err)
            q.put(None)
        except Exception:  # noqa: BLE001
            pass


def browser_ready() -> bool:
    return _BROWSER_READY.is_set()


def _emit(event: dict) -> None:
    if _BROADCAST is not None:
        _BROADCAST(event)


def fulfill(request_id: str, *, chunk: str = "", done: bool = False, error: str = "") -> bool:
    with _LOCK:
        pending = _PENDING.get(request_id)
    if pending is None:
        return False
    if error:
        pending.put(RuntimeError(error))
        pending.put(None)
        return True
    if chunk:
        pending.put(chunk)
    if done:
        pending.put(None)
    return True


def request_stream(messages: list[dict], *, timeout: float = DEFAULT_TIMEOUT) -> Iterator[str]:
    if not browser_ready():
        raise RuntimeError(
            "WebLLM browser bridge is offline — keep the Maya dashboard open in a "
            "WebGPU-capable browser (Chrome/Edge)."
        )
    request_id = str(uuid.uuid4())
    pending: queue.Queue[Any] = queue.Queue()
    with _LOCK:
        _PENDING[request_id] = pending
    try:
        _emit({
            "type": "webllm_request",
            "id": request_id,
            "messages": messages,
            "stream": True,
        })
        while True:
            try:
                item = pending.get(timeout=timeout)
            except queue.Empty as exc:
                raise TimeoutError(
                    "WebLLM inference timed out — is the dashboard tab open and the model loaded?"
                ) from exc
            if item is None:
                break
            if isinstance(item, BaseException):
                raise item
            yield str(item)
    finally:
        with _LOCK:
            _PENDING.pop(request_id, None)


def request_complete(messages: list[dict], *, timeout: float = DEFAULT_TIMEOUT) -> str:
    parts = list(request_stream(messages, timeout=timeout))
    return "".join(parts)
