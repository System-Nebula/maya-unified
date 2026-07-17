"""Browser WebSocket mic ingress → VoiceAgent."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import WebSocket, WebSocketDisconnect

from services.auth.deps import resolve_operator_from_token
from services.auth.operator_store import get_db_session
from services.auth.session import OPERATOR_SESSION_COOKIE, verify_operator_session
from services.voice.audio_protocol import (
    FRAME_HEADER_SIZE,
    MAX_PCM_BYTES,
    MAX_RAW_FRAME_BYTES,
    TARGET_INGRESS_RATE,
    AudioNegotiated,
    AudioProtocolError,
    FrameStreamState,
    audio_challenge_payload,
    negotiate_audio_hello,
    resample_s16le_mono,
    unpack_pcm_frame,
)
from services.voice.bounded_queue import async_put_keep_newest
from services.voice.duplex_ingress import (
    ChunkSignal,
    DuplexIngressSession,
    ingest_pcm_chunk,
    reset_hushmic_stream,
    utterance_pcm48_to_int16_16k,
)
from services.voice.hushmic import browser_key
from services.voice.hub import hub

log = logging.getLogger("maya-unified.voice.browser_ws")

# Brief reconnect window before an abandoned tab releases the voice lease.
DISCONNECT_GRACE_S = 8.0
# Application-level keepalive (Starlette may not surface WS ping frames to us).
HEARTBEAT_INTERVAL_S = 15.0
HEARTBEAT_TIMEOUT_S = 45.0
# Keep at most two finalized utterances pending ASR (drop oldest on overflow).
UTTERANCE_QUEUE_MAX = 2
# ~60 ms of mic frames at 20 ms/chunk — drop oldest latency, never block receive.
MIC_FRAME_QUEUE_MAX = 3


@dataclass
class ConnBackpressureStats:
    """Per-connection ingress observability (AUDIO-005)."""

    bytes_in: int = 0
    frames_in: int = 0
    frames_dropped_oversize: int = 0
    frames_dropped_queue: int = 0
    utterance_dropped: int = 0
    client_gap_events: int = 0
    window_started: float = field(default_factory=time.monotonic)
    last_enqueue_at: float | None = None

    def note_frame(self, nbytes: int) -> None:
        self.bytes_in += int(nbytes)
        self.frames_in += 1

    def bytes_per_sec(self, now: float | None = None) -> float:
        t = float(now if now is not None else time.monotonic())
        dt = max(0.001, t - self.window_started)
        return self.bytes_in / dt

    def queue_age_ms(self, now: float | None = None) -> float | None:
        if self.last_enqueue_at is None:
            return None
        t = float(now if now is not None else time.monotonic())
        return max(0.0, (t - self.last_enqueue_at) * 1000.0)

    def snapshot(self, *, mic_qsize: int = 0, utterance_qsize: int = 0) -> dict[str, Any]:
        return {
            "type": "backpressure",
            "bytes_in": self.bytes_in,
            "bytes_per_sec": round(self.bytes_per_sec(), 1),
            "frames_in": self.frames_in,
            "frames_dropped_oversize": self.frames_dropped_oversize,
            "frames_dropped_queue": self.frames_dropped_queue,
            "utterance_dropped": self.utterance_dropped,
            "client_gap_events": self.client_gap_events,
            "mic_queue_depth": mic_qsize,
            "utterance_queue_depth": utterance_qsize,
            "queue_age_ms": self.queue_age_ms(),
        }


def _ingest_frame_sync(
    session: DuplexIngressSession,
    pcm: bytes,
    *,
    sample_rate: int,
    enhancer_key: Any,
) -> tuple[ChunkSignal, bytes | None]:
    """HushMic + VAD — must not run on the ASGI event loop."""
    if sample_rate != TARGET_INGRESS_RATE:
        pcm = resample_s16le_mono(pcm, sample_rate, TARGET_INGRESS_RATE)
    return ingest_pcm_chunk(session, pcm, enhancer_key=enhancer_key)


@dataclass
class HeartbeatState:
    """Tracks liveness for one browser mic socket."""

    last_seen: float
    last_ping_sent: float = 0.0

    def touch(self, now: float | None = None) -> None:
        self.last_seen = float(now if now is not None else time.monotonic())

    def should_send_ping(
        self,
        now: float,
        *,
        interval_s: float = HEARTBEAT_INTERVAL_S,
    ) -> bool:
        return (now - self.last_ping_sent) >= float(interval_s)

    def should_timeout(
        self,
        now: float,
        *,
        timeout_s: float = HEARTBEAT_TIMEOUT_S,
    ) -> bool:
        return (now - self.last_seen) >= float(timeout_s)

    def mark_ping_sent(self, now: float | None = None) -> None:
        self.last_ping_sent = float(now if now is not None else time.monotonic())


@dataclass
class BrowserConnection:
    connection_id: str
    operator_id: str
    close: Callable[[], None]
    close_event: asyncio.Event = field(repr=False)


_registry_lock = threading.Lock()
_connections: dict[str, BrowserConnection] = {}
_abandon_tasks: dict[str, asyncio.Task] = {}


def _reset_connection_registry_for_tests() -> None:
    with _registry_lock:
        _connections.clear()
    for task in list(_abandon_tasks.values()):
        task.cancel()
    _abandon_tasks.clear()


def get_browser_connection_id(operator_id: str) -> str | None:
    with _registry_lock:
        conn = _connections.get(str(operator_id))
        return conn.connection_id if conn else None


def register_browser_connection(
    operator_id: str,
    close: Callable[[], None],
    *,
    close_event: asyncio.Event | None = None,
    connection_id: str | None = None,
) -> str:
    """Register the live mic socket for an operator; closes any previous socket only."""
    oid = str(operator_id)
    cid = connection_id or uuid.uuid4().hex
    event = close_event if close_event is not None else asyncio.Event()
    conn = BrowserConnection(
        connection_id=cid,
        operator_id=oid,
        close=close,
        close_event=event,
    )
    with _registry_lock:
        previous = _connections.get(oid)
        _connections[oid] = conn
    if previous is not None:
        try:
            previous.close()
        except Exception:  # noqa: BLE001
            pass
    _cancel_abandon(oid)
    return cid


def release_browser_connection(operator_id: str, connection_id: str) -> bool:
    """Compare-and-remove. Never touches a replacement connection."""
    oid = str(operator_id)
    with _registry_lock:
        current = _connections.get(oid)
        if current is None or current.connection_id != connection_id:
            return False
        _connections.pop(oid, None)
        return True


def register_disconnect_hook(operator_id: str, hook: Callable[[], None]) -> str:
    """Back-compat wrapper: register a close hook and return connection id."""
    return register_browser_connection(operator_id, hook)


def clear_disconnect_hook(operator_id: str) -> None:
    """Intentional stop: close and remove the current operator connection."""
    oid = str(operator_id)
    _cancel_abandon(oid)
    with _registry_lock:
        previous = _connections.pop(oid, None)
    if previous is not None:
        try:
            previous.close()
        except Exception:  # noqa: BLE001
            pass


def disconnect_all_browser_ws() -> None:
    """Signal every open browser mic WebSocket to exit (gateway shutdown/reload)."""
    for oid in list(_abandon_tasks):
        _cancel_abandon(oid)
    with _registry_lock:
        conns = list(_connections.values())
        _connections.clear()
    for conn in conns:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def _cancel_abandon(operator_id: str) -> None:
    task = _abandon_tasks.pop(str(operator_id), None)
    if task is not None and not task.done():
        task.cancel()


def _schedule_abandon_release(operator_id: str, connection_id: str) -> None:
    """If no replacement reconnects within the grace window, stop the voice session."""
    oid = str(operator_id)

    async def _run() -> None:
        try:
            await asyncio.sleep(DISCONNECT_GRACE_S)
        except asyncio.CancelledError:
            return
        if get_browser_connection_id(oid) is not None:
            return
        log.info(
            "browser ws abandon grace expired operator=%s connection=%s",
            oid,
            connection_id[:8],
        )
        try:
            hub.stop(operator_id=oid)
        except Exception as exc:  # noqa: BLE001
            log.warning("abandon stop failed operator=%s: %s", oid, exc)
        finally:
            _abandon_tasks.pop(oid, None)

    _cancel_abandon(oid)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _abandon_tasks[oid] = loop.create_task(_run())


async def _resolve_ws_operator(websocket: WebSocket) -> tuple[str | None, Any]:
    token = websocket.cookies.get(OPERATOR_SESSION_COOKIE)
    if not token:
        token = websocket.query_params.get("token")
    payload = verify_operator_session(token or "")
    if not payload:
        return None, None
    async for session in get_db_session():
        op = await resolve_operator_from_token(session, token)
        break
    else:
        op = None
    if op is None or getattr(op, "is_banned", False):
        return None, None
    return str(op.id), op


def _operator_has_voice_lease(operator_id: str) -> bool:
    lease = hub.voice_lease
    return (
        lease is not None
        and lease.kind == "operator"
        and lease.context_id == str(operator_id)
        and hub.agent is not None
        and hub.agent.is_session_running()
        and hub.agent.mic_source() == "browser"
    )


async def _send_json(ws: WebSocket, payload: dict) -> None:
    await ws.send_text(json.dumps(payload))


def _barge_terminal_payload(result: dict | None, *, assistant_speaking: bool) -> dict | None:
    if not assistant_speaking or not isinstance(result, dict):
        return None
    outcome = str(result.get("outcome") or "")
    if outcome == "clear_audio":
        payload = {"type": "clear_audio"}
        if isinstance(result.get("generation_id"), int):
            payload["generation_id"] = result["generation_id"]
        return payload
    if outcome in {"resume_audio", "ignored"}:
        return {"type": "resume_audio"}
    return None


def _process_utterance(pcm48: bytes, assistant_speaking: bool) -> dict:
    agent = hub.agent
    if agent is None:
        return {"outcome": "resume_audio" if assistant_speaking else "ignored"}
    audio_16k = utterance_pcm48_to_int16_16k(pcm48)
    if audio_16k.size == 0:
        agent._emit(type="status", value="listening")
        return {"outcome": "resume_audio" if assistant_speaking else "ignored"}
    return agent.submit_browser_utterance(audio_16k, assistant_speaking=assistant_speaking)


async def browser_voice_websocket(websocket: WebSocket) -> None:
    operator_id, _op = await _resolve_ws_operator(websocket)
    if not operator_id:
        await websocket.close(code=4401)
        return

    if not hub.ready or hub.agent is None:
        await websocket.close(code=1013)
        return

    if not _operator_has_voice_lease(operator_id):
        await websocket.close(code=4403)
        return

    # POST /start already applied context on the HTTP worker; only re-apply after
    # reconnect when the active operator differs (must not call run_sync on this loop).
    if (hub._active_operator_id or "") != str(operator_id):
        await asyncio.to_thread(hub.apply_operator_context, operator_id)

    await websocket.accept()

    session = DuplexIngressSession()
    closed = asyncio.Event()
    connection_id = uuid.uuid4().hex
    session_id = getattr(hub.agent, "_session_id", None)
    enh_key = browser_key(session_id, connection_id=connection_id)
    # Reset only this browser session's enhancer — never Discord / other keys.
    reset_hushmic_stream(enh_key)

    def _request_close() -> None:
        closed.set()

    register_browser_connection(
        operator_id,
        _request_close,
        close_event=closed,
        connection_id=connection_id,
    )
    await _send_json(
        websocket,
        audio_challenge_payload(connection_id=connection_id, session_id=session_id),
    )

    heartbeat = HeartbeatState(last_seen=time.monotonic())
    unexpected_disconnect = True
    negotiated: AudioNegotiated | None = None
    frame_state = FrameStreamState()
    stats = ConnBackpressureStats()
    mic_q: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=MIC_FRAME_QUEUE_MAX)
    utterance_q: asyncio.Queue[tuple[bytes, bool] | None] = asyncio.Queue(
        maxsize=UTTERANCE_QUEUE_MAX
    )

    async def _emit_backpressure(*, force: bool = False) -> None:
        if not force and stats.frames_dropped_queue == 0 and stats.frames_dropped_oversize == 0:
            return
        await _send_json(
            websocket,
            stats.snapshot(mic_qsize=mic_q.qsize(), utterance_qsize=utterance_q.qsize()),
        )

    async def _handle_ingress_signal(signal: ChunkSignal, pcm48: bytes | None) -> None:
        if signal == ChunkSignal.DUCK:
            await _send_json(websocket, {"type": "duck_audio"})
        elif signal == ChunkSignal.INTERRUPT:
            agent = hub.agent
            clear_gen = None
            if agent is not None:
                agent._barge_in_flag.set()
                clear_gen = agent.playback.stop()
                agent._emit(type="barge_in")
            payload = {"type": "clear_audio"}
            if clear_gen is not None:
                payload["generation_id"] = clear_gen
            await _send_json(websocket, payload)
        elif signal == ChunkSignal.FINALIZE and pcm48:
            dropped = await async_put_keep_newest(
                utterance_q, (pcm48, session.assistant_speaking)
            )
            if dropped:
                stats.utterance_dropped += 1
                await _send_json(
                    websocket,
                    {
                        "type": "busy",
                        "reason": "utterance_overflow",
                        "dropped": stats.utterance_dropped,
                    },
                )
                await _emit_backpressure(force=True)

    async def _heartbeat_loop() -> None:
        while not closed.is_set():
            try:
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                return
            if closed.is_set():
                return
            now = time.monotonic()
            if heartbeat.should_timeout(now):
                log.info(
                    "browser ws heartbeat timeout operator=%s connection=%s",
                    operator_id,
                    connection_id[:8],
                )
                closed.set()
                try:
                    await websocket.close(code=4000)
                except Exception:  # noqa: BLE001
                    pass
                return
            if heartbeat.should_send_ping(now):
                try:
                    await _send_json(
                        websocket,
                        {"type": "ping", "ts": time.time(), "connection_id": connection_id},
                    )
                    heartbeat.mark_ping_sent(now)
                    if stats.frames_in > 0:
                        await _emit_backpressure(force=True)
                except Exception:  # noqa: BLE001
                    closed.set()
                    return

    async def _audio_worker() -> None:
        """Enhance + VAD off the receive path (never block ASGI on HushMic)."""
        while not closed.is_set():
            try:
                raw = await asyncio.wait_for(mic_q.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                return
            if raw is None:
                mic_q.task_done()
                return
            try:
                if negotiated is None:
                    continue
                try:
                    pcm, _seq, _sample_index, _flags = unpack_pcm_frame(raw, frame_state)
                except AudioProtocolError as exc:
                    frame_state.drop_count += 1
                    await _send_json(
                        websocket,
                        {
                            "type": "error",
                            "message": f"bad audio frame: {exc}",
                            "gap_count": frame_state.gap_count,
                            "drop_count": frame_state.drop_count,
                        },
                    )
                    session.reset_on_gap()
                    frame_state.last_sequence = None
                    frame_state.last_sample_index = None
                    continue
                signal, pcm48 = await asyncio.to_thread(
                    _ingest_frame_sync,
                    session,
                    pcm,
                    sample_rate=negotiated.sample_rate,
                    enhancer_key=enh_key,
                )
                await _handle_ingress_signal(signal, pcm48)
            except Exception as exc:  # noqa: BLE001
                log.warning("browser audio worker error: %s", exc)
            finally:
                try:
                    mic_q.task_done()
                except ValueError:
                    pass

    async def _asr_worker() -> None:
        """Process finalized utterances without blocking the receive loop."""
        while not closed.is_set():
            try:
                item = await asyncio.wait_for(utterance_q.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                return
            if item is None:
                utterance_q.task_done()
                return
            pcm48, assistant_speaking = item
            try:
                await _send_json(websocket, {"type": "transcribing"})
                result = await asyncio.to_thread(_process_utterance, pcm48, assistant_speaking)
                terminal = _barge_terminal_payload(
                    result, assistant_speaking=assistant_speaking
                )
                if terminal is not None:
                    await _send_json(websocket, terminal)
            except Exception as exc:  # noqa: BLE001
                log.warning("browser asr worker error: %s", exc)
                if assistant_speaking:
                    await _send_json(websocket, {"type": "resume_audio"})
            finally:
                try:
                    utterance_q.task_done()
                except ValueError:
                    pass

    hb_task = asyncio.create_task(_heartbeat_loop())
    audio_task = asyncio.create_task(_audio_worker())
    asr_task = asyncio.create_task(_asr_worker())
    try:
        while not closed.is_set():
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            if message.get("type") == "websocket.disconnect":
                break

            if message.get("bytes") is not None:
                heartbeat.touch()
                if negotiated is None:
                    await _send_json(
                        websocket,
                        {
                            "type": "error",
                            "message": "send audio_hello before PCM frames",
                        },
                    )
                    continue
                raw_chunk = message["bytes"]
                stats.note_frame(len(raw_chunk))
                # Reject oversized frames before NumPy / unpack.
                if len(raw_chunk) > MAX_RAW_FRAME_BYTES:
                    stats.frames_dropped_oversize += 1
                    await _send_json(
                        websocket,
                        {
                            "type": "error",
                            "message": "audio frame too large",
                            "max_bytes": MAX_RAW_FRAME_BYTES,
                            "drop_count": stats.frames_dropped_oversize,
                        },
                    )
                    await _emit_backpressure(force=True)
                    continue
                if len(raw_chunk) < FRAME_HEADER_SIZE:
                    stats.frames_dropped_oversize += 1
                    continue
                dropped = await async_put_keep_newest(mic_q, raw_chunk)
                stats.last_enqueue_at = time.monotonic()
                if dropped:
                    stats.frames_dropped_queue += 1
                    session.reset_on_gap()
                    frame_state.last_sequence = None
                    frame_state.last_sample_index = None
                    frame_state.gap_count += 1
                    await _send_json(
                        websocket,
                        {
                            "type": "busy",
                            "reason": "mic_frame_overflow",
                            "dropped": stats.frames_dropped_queue,
                        },
                    )
                    await _emit_backpressure(force=True)

            elif message.get("text") is not None:
                heartbeat.touch()
                try:
                    event = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue

                if event.get("type") == "audio_hello":
                    try:
                        negotiated = negotiate_audio_hello(event)
                    except AudioProtocolError as exc:
                        await _send_json(
                            websocket,
                            {"type": "error", "message": f"audio_hello rejected: {exc}"},
                        )
                        continue
                    frame_state = FrameStreamState()
                    await _send_json(
                        websocket,
                        {
                            "type": "ready",
                            "connection_id": connection_id,
                            "session_id": session_id,
                            "protocol": negotiated.protocol,
                            "format": negotiated.format,
                            "sample_rate": negotiated.sample_rate,
                            "ingress_sample_rate": TARGET_INGRESS_RATE,
                            "channels": negotiated.channels,
                            "frames_per_chunk": negotiated.frames_per_chunk,
                            "max_pcm_bytes": MAX_PCM_BYTES,
                            "max_raw_frame_bytes": MAX_RAW_FRAME_BYTES,
                            "mic_queue_max": MIC_FRAME_QUEUE_MAX,
                            "heartbeat_interval_s": HEARTBEAT_INTERVAL_S,
                            "heartbeat_timeout_s": HEARTBEAT_TIMEOUT_S,
                        },
                    )
                    continue

                if event.get("type") == "client_gap":
                    stats.client_gap_events += 1
                    session.reset_on_gap()
                    frame_state.last_sequence = None
                    frame_state.last_sample_index = None
                    frame_state.gap_count += 1
                    await _emit_backpressure(force=True)
                    continue

                if event.get("type") == "pong":
                    continue

                if event.get("type") in {
                    "playback_started",
                    "playback_progress",
                    "playback_ended",
                    "playback_interrupted",
                    "audio_queued",
                }:
                    agent = hub.agent
                    accepted = agent is not None and agent.playback.note_playback_ack(event)
                    if accepted and event.get("type") in ("playback_started", "playback_progress"):
                        session.set_assistant_speaking(True)
                    elif accepted and event.get("type") in ("playback_ended", "playback_interrupted"):
                        session.set_assistant_speaking(False)
                    continue

                if event.get("type") == "interrupt":
                    agent = hub.agent
                    clear_gen = None
                    if agent is not None:
                        agent._barge_in_flag.set()
                        clear_gen = agent.playback.stop()
                        agent._emit(type="barge_in")
                    payload = {"type": "clear_audio"}
                    if clear_gen is not None:
                        payload["generation_id"] = clear_gen
                    await _send_json(websocket, payload)

                elif event.get("type") == "playback_state":
                    session.set_assistant_speaking(bool(event.get("speaking")))
                    agent = hub.agent
                    if agent is not None and not bool(event.get("speaking")):
                        # Legacy speaking=false — treat as soft ended hint only when idle.
                        pass

    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        unexpected_disconnect = False
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("browser voice ws error: %s", exc)
    finally:
        closed.set()
        for q in (mic_q, utterance_q):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(None)
                except asyncio.QueueFull:
                    pass
        for task in (audio_task, asr_task, hb_task):
            task.cancel()
        for task in (audio_task, asr_task, hb_task):
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                pass
        # Compare-and-remove only this connection. Never clear/invoke a replacement.
        was_current = release_browser_connection(operator_id, connection_id)
        # Intentional stop/replacement already removed us from the registry.
        # Unexpected drop or heartbeat timeout still owns the slot → grace period.
        if was_current and unexpected_disconnect:
            _schedule_abandon_release(operator_id, connection_id)
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
