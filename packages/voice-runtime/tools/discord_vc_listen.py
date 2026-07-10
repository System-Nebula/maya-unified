"""Pycord voice-receive sink: per-user PCM → silence-bounded utterances for STT.

Compatible with py-cord 2.8+ AudioReader, which calls ``sink.write(VoiceData, source)``
and expects ``__sink_listeners__`` / ``walk_children`` on the sink.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from observability import get_logger

log = get_logger("discord.vc_listen")

UtteranceCallback = Callable[[dict[str, Any]], None]


@dataclass
class _UserBuf:
    chunks: list[bytes]
    last_write_at: float
    started_at: float
    bytes_total: int = 0
    peak_energy: float = 0.0


@dataclass
class _PendingUtterance:
    payload: dict[str, Any]
    ready_at: float
    chunks_16k: list[np.ndarray] = field(default_factory=list)


def pcm_stereo_48k_to_mono_16k(pcm: bytes) -> np.ndarray:
    """Convert Discord PCM (48 kHz stereo s16le) to Whisper-friendly mono 16 kHz."""
    if not pcm:
        return np.zeros(0, dtype=np.int16)
    raw = np.frombuffer(pcm, dtype=np.int16)
    if raw.size < 2:
        return np.zeros(0, dtype=np.int16)
    if raw.size % 2:
        raw = raw[:-1]
    mono = raw.reshape(-1, 2).astype(np.float32).mean(axis=1)
    down = mono[::3]
    return np.clip(down, -32768, 32767).astype(np.int16)


def _pcm_rms(pcm: bytes) -> float:
    if len(pcm) < 4:
        return 0.0
    raw = np.frombuffer(pcm, dtype=np.int16)
    if raw.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(raw.astype(np.float32) ** 2)))


def _extract_pcm_and_user(
    data: Any,
    user: Any,
    *,
    voice_client: Any = None,
) -> tuple[bytes, int | None]:
    """Normalize py-cord 2.8 VoiceData write() args to (pcm_bytes, user_id)."""
    pcm: bytes = b""
    uid: int | None = None

    pcm_attr = getattr(data, "pcm", None)
    if isinstance(pcm_attr, (bytes, bytearray)):
        pcm = bytes(pcm_attr)
        src = getattr(data, "source", None) or user
    elif isinstance(data, (bytes, bytearray)):
        pcm = bytes(data)
        src = user
    else:
        src = user

    if isinstance(src, int):
        uid = src
    elif src is not None:
        try:
            uid = int(getattr(src, "id", src))
        except (TypeError, ValueError):
            uid = None

    if uid is None and voice_client is not None:
        try:
            packet = getattr(data, "packet", None)
            ssrc = getattr(packet, "ssrc", None)
            if ssrc is not None:
                uid = getattr(voice_client, "_ssrc_to_id", {}).get(int(ssrc))
                if uid is not None:
                    uid = int(uid)
        except (TypeError, ValueError, AttributeError):
            uid = None

    return pcm, uid


def build_utterance_sink(
    *,
    on_utterance: UtteranceCallback,
    bot_user_id: int | None = None,
    silence_ms: float = 1600.0,
    min_ms: float = 700.0,
    max_ms: float = 16000.0,
    energy_threshold: float = 90.0,
    merge_ms: float = 1200.0,
    voice_client: Any = None,
):
    """Build a py-cord Sink that emits per-user utterances on silence.

    End-of-utterance is based on **no PCM writes** for ``silence_ms`` (Discord
    client VAD stopped sending), not mid-phrase energy dips. Short back-to-back
    flushes from the same user are merged before STT.
    """
    from discord.sinks import Filters, Sink, default_filters

    _bytes_per_sec = 48000 * 2 * 2

    class UtteranceSink(Sink):
        __sink_listeners__: list[tuple[str, str]] = []

        def __init__(self) -> None:
            filters = dict(default_filters)
            super().__init__(filters=filters)
            self.encoding = "pcm"
            self.vc = voice_client
            self._on_utterance = on_utterance
            self._bot_user_id = bot_user_id
            self._silence_sec = max(0.35, silence_ms / 1000.0)
            self._min_sec = max(0.25, min_ms / 1000.0)
            self._max_sec = max(self._min_sec + 0.5, max_ms / 1000.0)
            self._energy_threshold = energy_threshold
            self._merge_sec = max(0.15, merge_ms / 1000.0)
            self._bufs: dict[int, _UserBuf] = {}
            self._pending: dict[int, _PendingUtterance] = {}
            self._lock = threading.Lock()
            self._stop = threading.Event()
            self._watch = threading.Thread(
                target=self._watchdog,
                name="discord-vc-utterance",
                daemon=True,
            )
            self._watch.start()
            self._channel_name = ""
            self._guild_name = ""
            self._guild_id: int | None = None
            self._write_logs = 0
            self._drop_logs = 0

        def walk_children(self, *, with_self: bool = False) -> Iterator[Sink]:
            if with_self:
                yield self
            return
            yield  # pragma: no cover

        def is_opus(self) -> bool:
            return False

        def set_channel_meta(
            self,
            *,
            channel_name: str = "",
            guild_name: str = "",
            guild_id: int | None = None,
        ) -> None:
            self._channel_name = channel_name or ""
            self._guild_name = guild_name or ""
            self._guild_id = guild_id

        def format_audio(self, audio) -> None:  # noqa: ANN001
            return

        @Filters.container
        def write(self, data, user):  # noqa: ANN001
            pcm, uid = _extract_pcm_and_user(data, user, voice_client=self.vc)
            if not pcm or uid is None:
                self._drop_logs += 1
                if self._drop_logs <= 5 or self._drop_logs % 50 == 0:
                    log.info(
                        "vc sink drop pcm=%s uid=%s source=%s (n=%s)",
                        len(pcm) if pcm else 0,
                        uid,
                        type(user).__name__ if user is not None else None,
                        self._drop_logs,
                    )
                return
            if self._bot_user_id and uid == self._bot_user_id:
                return
            now = time.monotonic()
            energy = _pcm_rms(pcm)
            self._write_logs += 1
            if self._write_logs <= 3 or self._write_logs % 100 == 0:
                log.info(
                    "vc sink write user=%s pcm=%s energy=%.1f (n=%s)",
                    uid,
                    len(pcm),
                    energy,
                    self._write_logs,
                )
            with self._lock:
                # New speech while a merge window is open → fold into pending.
                pending = self._pending.get(uid)
                buf = self._bufs.get(uid)
                if buf is None:
                    if energy < self._energy_threshold and pending is None:
                        return
                    buf = _UserBuf(
                        chunks=[],
                        last_write_at=now,
                        started_at=now,
                        peak_energy=energy,
                    )
                    self._bufs[uid] = buf
                    log.info("vc utterance start user=%s energy=%.1f", uid, energy)
                buf.chunks.append(pcm)
                buf.bytes_total += len(pcm)
                buf.last_write_at = now  # any packet = still in phrase
                buf.peak_energy = max(buf.peak_energy, energy)
                if now - buf.started_at >= self._max_sec:
                    self._flush_user_locked(uid, reason="max_duration")

        def _watchdog(self) -> None:
            while not self._stop.wait(0.1):
                try:
                    self._flush_silent()
                    self._emit_pending()
                except Exception as exc:  # noqa: BLE001
                    log.debug("vc utterance watchdog: %s", exc)

        def _flush_silent(self) -> None:
            now = time.monotonic()
            with self._lock:
                due = [
                    uid
                    for uid, buf in self._bufs.items()
                    if (now - buf.last_write_at) >= self._silence_sec
                    and (now - buf.started_at) >= self._min_sec
                ]
                for uid in due:
                    self._flush_user_locked(uid, reason="silence")

        def _flush_user_locked(self, uid: int, *, reason: str) -> None:
            buf = self._bufs.pop(uid, None)
            if buf is None or not buf.chunks:
                return
            duration = buf.bytes_total / float(_bytes_per_sec)
            if duration < self._min_sec * 0.5 and reason != "max_duration":
                log.info(
                    "vc utterance discard user=%s reason=%s dur=%.2f (too short)",
                    uid,
                    reason,
                    duration,
                )
                return
            pcm = b"".join(buf.chunks)
            mono = pcm_stereo_48k_to_mono_16k(pcm)
            if mono.size < 1600:
                log.info(
                    "vc utterance discard user=%s samples=%s (too small)",
                    uid,
                    mono.size,
                )
                return

            pending = self._pending.get(uid)
            if pending is not None:
                pending.chunks_16k.append(mono)
                pending.ready_at = time.monotonic() + self._merge_sec
                pending.payload["duration_sec"] = round(
                    sum(c.size for c in pending.chunks_16k) / 16000.0, 3
                )
                log.info(
                    "vc utterance merge user=%s +%.2fs -> %.2fs",
                    uid,
                    duration,
                    pending.payload["duration_sec"],
                )
                return

            member = None
            try:
                if self.vc and getattr(self.vc, "guild", None):
                    member = self.vc.guild.get_member(uid)
            except Exception:  # noqa: BLE001
                member = None
            display = getattr(member, "display_name", None) or str(uid)
            ch = getattr(self.vc, "channel", None) if self.vc else None
            guild = getattr(self.vc, "guild", None) if self.vc else None
            payload = {
                "author": display,
                "author_id": uid,
                "sample_rate": 16000,
                "duration_sec": round(float(mono.size) / 16000.0, 3),
                "channel": self._channel_name or (getattr(ch, "name", "") if ch else ""),
                "guild": self._guild_name or (getattr(guild, "name", "") if guild else ""),
                "guild_id": self._guild_id
                or (getattr(guild, "id", None) if guild else None),
                "reason": reason,
            }
            self._pending[uid] = _PendingUtterance(
                payload=payload,
                ready_at=time.monotonic() + self._merge_sec,
                chunks_16k=[mono],
            )
            log.info(
                "vc utterance hold user=%s reason=%s dur=%.2fs (merge window %.0fms)",
                display,
                reason,
                payload["duration_sec"],
                self._merge_sec * 1000,
            )

        def _emit_pending(self) -> None:
            now = time.monotonic()
            to_emit: list[tuple[int, _PendingUtterance]] = []
            with self._lock:
                # Don't emit while the user still has an open live buffer.
                for uid, pending in list(self._pending.items()):
                    if uid in self._bufs:
                        pending.ready_at = now + self._merge_sec
                        continue
                    if now >= pending.ready_at:
                        to_emit.append((uid, self._pending.pop(uid)))
            for uid, pending in to_emit:
                mono = np.concatenate(pending.chunks_16k)
                payload = dict(pending.payload)
                payload["pcm_mono_16k"] = mono
                payload["duration_sec"] = round(float(mono.size) / 16000.0, 3)
                log.info(
                    "vc utterance flush user=%s reason=%s dur=%.2fs samples=%s",
                    payload.get("author") or uid,
                    payload.get("reason"),
                    payload["duration_sec"],
                    mono.size,
                )
                try:
                    self._on_utterance(payload)
                except Exception as exc:  # noqa: BLE001
                    log.warning("vc utterance callback failed: %s", exc)

        def cleanup(self) -> None:
            self._stop.set()
            with self._lock:
                uids = list(self._bufs)
                for uid in uids:
                    self._flush_user_locked(uid, reason="cleanup")
                # Force-emit anything still held.
                for uid, pending in list(self._pending.items()):
                    pending.ready_at = 0
            self._emit_pending()
            self.finished = True

    return UtteranceSink()
