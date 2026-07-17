"""Coordinate in-browser WebLLM inference for server-side voice turns (SEC-005).

State is keyed by ``(operator_id, connection_id)``. A request ID alone is never
authorization — fulfill requires the owning operator and connection, and rejects
stale generations / duplicate completions.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Callable

BroadcastFn = Callable[..., None]

_BROADCAST: BroadcastFn | None = None
_READY: dict[tuple[str, str], float] = {}
_PENDING: dict[str, "PendingRequest"] = {}
_LOCK = threading.Lock()
DEFAULT_TIMEOUT = 180.0


@dataclass(frozen=True)
class WebLLMClientKey:
    operator_id: str
    connection_id: str

    @property
    def as_tuple(self) -> tuple[str, str]:
        return self.operator_id, self.connection_id


@dataclass
class PendingRequest:
    request_id: str
    owner_operator_id: str
    connection_id: str
    turn_id: str | None = None
    generation_id: int | None = None
    expires_at: float = 0.0
    cancel: threading.Event = field(default_factory=threading.Event)
    queue: queue.Queue[Any] = field(default_factory=queue.Queue)
    closed: bool = False
    cancel_reason: str = ""


def set_broadcast(fn: BroadcastFn) -> None:
    global _BROADCAST
    _BROADCAST = fn


def _emit(event: dict, *, operator_id: str | None = None) -> None:
    if _BROADCAST is None:
        return
    if operator_id:
        from services.voice.audience import Audience

        event = {**event, "audience": Audience.operator(str(operator_id)).to_dict()}
        _BROADCAST(event, operator_id=str(operator_id))
    else:
        _BROADCAST(event)


def _reset_for_tests() -> None:
    with _LOCK:
        _READY.clear()
        pending = list(_PENDING.values())
        _PENDING.clear()
    for p in pending:
        p.cancel.set()
        try:
            p.queue.put(None)
        except Exception:  # noqa: BLE001
            pass


def mark_browser_ready(
    operator_id: str,
    connection_id: str,
    ready: bool = True,
) -> None:
    oid = str(operator_id or "").strip()
    cid = str(connection_id or "").strip()
    if not oid or not cid:
        raise ValueError("operator_id and connection_id are required")
    key = (oid, cid)
    if ready:
        with _LOCK:
            _READY[key] = time.monotonic()
        return
    with _LOCK:
        _READY.pop(key, None)
        doomed = [
            p
            for p in _PENDING.values()
            if p.owner_operator_id == oid and p.connection_id == cid
        ]
    _fail_pending(doomed, "WebLLM connection disconnected")


def request_browser_unload(*, operator_id: str | None = None) -> None:
    """Tell dashboard tabs to drop the in-browser model and free WebGPU memory."""
    if operator_id:
        oid = str(operator_id)
        with _LOCK:
            keys = [k for k in _READY if k[0] == oid]
            for k in keys:
                _READY.pop(k, None)
            doomed = [p for p in _PENDING.values() if p.owner_operator_id == oid]
            for p in doomed:
                _PENDING.pop(p.request_id, None)
        _fail_pending(doomed, "WebLLM unloaded")
        _emit({"type": "webllm_unload"}, operator_id=oid)
        return

    with _LOCK:
        operators = sorted({k[0] for k in _READY})
        pending = list(_PENDING.values())
        _READY.clear()
        _PENDING.clear()
    _fail_pending(pending, "WebLLM unloaded")
    for oid in operators:
        _emit({"type": "webllm_unload"}, operator_id=oid)


def cancel_pending(reason: str = "WebLLM bridge reset") -> None:
    """Fail any in-flight browser inference requests."""
    with _LOCK:
        pending = list(_PENDING.values())
        _PENDING.clear()
    _fail_pending(pending, reason)


def cancel_operator_pending(operator_id: str, reason: str = "session stop") -> None:
    oid = str(operator_id or "").strip()
    if not oid:
        return
    with _LOCK:
        doomed = [p for p in list(_PENDING.values()) if p.owner_operator_id == oid]
        for p in doomed:
            _PENDING.pop(p.request_id, None)
    _fail_pending(doomed, reason)


def _fail_pending(pending: list[PendingRequest], reason: str) -> None:
    err = RuntimeError(reason)
    for p in pending:
        p.cancel_reason = reason
        p.cancel.set()
        p.closed = True
        try:
            p.queue.put(err)
            p.queue.put(None)
        except Exception:  # noqa: BLE001
            pass


def browser_ready(*, operator_id: str | None = None) -> bool:
    with _LOCK:
        if operator_id:
            oid = str(operator_id)
            return any(k[0] == oid for k in _READY)
        return bool(_READY)


def select_ready_connection(operator_id: str) -> str | None:
    """Pick the most recently ready connection for an operator."""
    oid = str(operator_id or "").strip()
    if not oid:
        return None
    with _LOCK:
        candidates = [(ts, cid) for (op, cid), ts in _READY.items() if op == oid]
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def fulfill(
    request_id: str,
    *,
    operator_id: str,
    connection_id: str,
    chunk: str = "",
    done: bool = False,
    error: str = "",
    generation_id: int | None = None,
) -> bool:
    """Deliver a chunk/completion. Returns False when unauthorized or stale."""
    rid = str(request_id or "").strip()
    oid = str(operator_id or "").strip()
    cid = str(connection_id or "").strip()
    if not rid or not oid or not cid:
        return False

    with _LOCK:
        pending = _PENDING.get(rid)
        if pending is None:
            return False
        if pending.owner_operator_id != oid or pending.connection_id != cid:
            return False
        if pending.closed:
            return False
        if pending.cancel.is_set():
            return False
        if (
            pending.generation_id is not None
            and generation_id is not None
            and int(generation_id) != int(pending.generation_id)
        ):
            return False
        if time.monotonic() > pending.expires_at:
            _PENDING.pop(rid, None)
            pending.closed = True
            return False

        if error:
            pending.closed = True
            _PENDING.pop(rid, None)
            pending.queue.put(RuntimeError(error))
            pending.queue.put(None)
            return True
        if chunk:
            pending.queue.put(chunk)
        if done:
            pending.closed = True
            _PENDING.pop(rid, None)
            pending.queue.put(None)
        return True


def request_stream(
    messages: list[dict],
    *,
    operator_id: str,
    connection_id: str | None = None,
    turn_id: str | None = None,
    generation_id: int | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Iterator[str]:
    oid = str(operator_id or "").strip()
    if not oid:
        raise RuntimeError("WebLLM request requires an operator_id owner")
    if not browser_ready(operator_id=oid):
        raise RuntimeError(
            "WebLLM browser bridge is offline — keep the Maya dashboard open in a "
            "WebGPU-capable browser (Chrome/Edge)."
        )
    cid = str(connection_id or "").strip() or select_ready_connection(oid)
    if not cid:
        raise RuntimeError("No ready WebLLM connection for this operator")

    request_id = str(uuid.uuid4())
    pending = PendingRequest(
        request_id=request_id,
        owner_operator_id=oid,
        connection_id=cid,
        turn_id=str(turn_id) if turn_id else None,
        generation_id=int(generation_id) if generation_id is not None else None,
        expires_at=time.monotonic() + float(timeout),
    )
    with _LOCK:
        _PENDING[request_id] = pending
    try:
        event = {
            "type": "webllm_request",
            "id": request_id,
            "connection_id": cid,
            "operator_id": oid,
            "messages": messages,
            "stream": True,
        }
        if pending.turn_id:
            event["turn_id"] = pending.turn_id
        if pending.generation_id is not None:
            event["generation_id"] = pending.generation_id
        _emit(event, operator_id=oid)
        while True:
            if pending.cancel.is_set():
                raise RuntimeError(pending.cancel_reason or "WebLLM request cancelled")
            if time.monotonic() > pending.expires_at:
                raise TimeoutError(
                    "WebLLM inference timed out — is the dashboard tab open and the model loaded?"
                )
            try:
                item = pending.queue.get(timeout=min(1.0, timeout))
            except queue.Empty:
                continue
            if item is None:
                break
            if isinstance(item, BaseException):
                raise item
            yield str(item)
    finally:
        with _LOCK:
            _PENDING.pop(request_id, None)
        pending.closed = True


def request_complete(
    messages: list[dict],
    *,
    operator_id: str,
    connection_id: str | None = None,
    turn_id: str | None = None,
    generation_id: int | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    parts = list(
        request_stream(
            messages,
            operator_id=operator_id,
            connection_id=connection_id,
            turn_id=turn_id,
            generation_id=generation_id,
            timeout=timeout,
        )
    )
    return "".join(parts)


def pending_snapshot_for_tests() -> dict[str, dict[str, Any]]:
    with _LOCK:
        return {
            rid: {
                "owner_operator_id": p.owner_operator_id,
                "connection_id": p.connection_id,
                "turn_id": p.turn_id,
                "generation_id": p.generation_id,
                "closed": p.closed,
            }
            for rid, p in _PENDING.items()
        }


def ready_clients_for_tests() -> list[tuple[str, str]]:
    with _LOCK:
        return sorted(_READY.keys())
