"""Pycord voice-receive sink: per-user PCM → silence-bounded utterances for STT."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import numpy as np

from observability import get_logger

log = get_logger("discord.vc_listen")

# Discord Opus decoder output (py-cord Decoder defaults).
DISCORD_CHANNELS = 2
DISCORD_SAMPLE_RATE = 48000
DISCORD_SAMPLE_WIDTH = 2  # bytes per sample per channel

UtteranceCallback = Callable[[dict[str, Any]], None]


@dataclass
class _UserBuf:
    chunks: list[bytes]
    last_voice_at: float
    started_at: float
    bytes_total: int = 0


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
    # 48000 / 16000 = 3
    down = mono[::3]
    return np.clip(down, -32768, 32767).astype(np.int16)


def _pcm_rms(pcm: bytes) -> float:
    if len(pcm) < 4:
        return 0.0
    raw = np.frombuffer(pcm, dtype=np.int16)
    if raw.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(raw.astype(np.float32) ** 2)))


def build_utterance_sink(
    *,
    on_utterance: UtteranceCallback,
    bot_user_id: int | None = None,
    silence_ms: float = 750.0,
    min_ms: float = 450.0,
    max_ms: float = 14000.0,
    energy_threshold: float = 220.0,
):
    """Build a py-cord Sink that emits per-user utterances on silence."""
    import discord
    from discord.sinks import Filters, Sink, default_filters

    class UtteranceSink(Sink):
        def __init__(self) -> None:
            filters = dict(default_filters)
            super().__init__(filters=filters)
            self.encoding = "pcm"
            self._on_utterance = on_utterance
            self._bot_user_id = bot_user_id
            self._silence_sec = max(0.2, silence_ms / 1000.0)
            self._min_sec = max(0.2, min_ms / 1000.0)
            self._max_sec = max(self._min_sec + 0.5, max_ms / 1000.0)
            self._energy_threshold = energy_threshold
            self._bufs: dict[int, _UserBuf] = {}
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
            # Live sink — no post-hoc file formatting.
            return

        @Filters.container
        def write(self, data, user):  # noqa: ANN001
            if not data or user is None:
                return
            try:
                uid = int(user)
            except (TypeError, ValueError):
                return
            if self._bot_user_id and uid == self._bot_user_id:
                return
            now = time.monotonic()
            energy = _pcm_rms(data)
            with self._lock:
                buf = self._bufs.get(uid)
                if buf is None:
                    if energy < self._energy_threshold:
                        return
                    buf = _UserBuf(chunks=[], last_voice_at=now, started_at=now)
                    self._bufs[uid] = buf
                buf.chunks.append(data)
                buf.bytes_total += len(data)
                if energy >= self._energy_threshold:
                    buf.last_voice_at = now
                elapsed = now - buf.started_at
                if elapsed >= self._max_sec:
                    self._flush_user_locked(uid, reason="max_duration")

        def _watchdog(self) -> None:
            while not self._stop.wait(0.12):
                try:
                    self._flush_silent()
                except Exception as exc:  # noqa: BLE001
                    log.debug("vc utterance watchdog: %s", exc)

        def _flush_silent(self) -> None:
            now = time.monotonic()
            with self._lock:
                due = [
                    uid
                    for uid, buf in self._bufs.items()
                    if (now - buf.last_voice_at) >= self._silence_sec
                    and (now - buf.started_at) >= self._min_sec
                ]
                for uid in due:
                    self._flush_user_locked(uid, reason="silence")

        def _flush_user_locked(self, uid: int, *, reason: str) -> None:
            buf = self._bufs.pop(uid, None)
            if buf is None or not buf.chunks:
                return
            duration = max(0.0, buf.last_voice_at - buf.started_at)
            if duration < self._min_sec * 0.6 and reason != "max_duration":
                return
            pcm = b"".join(buf.chunks)
            mono = pcm_stereo_48k_to_mono_16k(pcm)
            if mono.size < 1600:  # <100 ms @ 16 kHz
                return
            member = None
            try:
                if self.vc and self.vc.guild:
                    member = self.vc.guild.get_member(uid)
            except Exception:  # noqa: BLE001
                member = None
            display = getattr(member, "display_name", None) or str(uid)
            payload = {
                "author": display,
                "author_id": uid,
                "pcm_mono_16k": mono,
                "sample_rate": 16000,
                "duration_sec": round(float(mono.size) / 16000.0, 3),
                "channel": self._channel_name
                or (self.vc.channel.name if self.vc and self.vc.channel else ""),
                "guild": self._guild_name
                or (self.vc.guild.name if self.vc and self.vc.guild else ""),
                "guild_id": self._guild_id
                or (self.vc.guild.id if self.vc and self.vc.guild else None),
                "reason": reason,
            }
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
            self.finished = True

    return UtteranceSink()
