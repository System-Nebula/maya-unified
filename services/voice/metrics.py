"""OBS-001: voice latency and queue metrics (IDs/numbers only — no content)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

# Histograms from plan.md OBS-001
VOICE_HISTOGRAMS: tuple[str, ...] = (
    "voice.endpoint.ms",
    "voice.asr.queue_ms",
    "voice.asr.ms",
    "voice.llm.ttft_ms",
    "voice.tts.ttfa_ms",
    "voice.e2e.first_audio_ms",
    "voice.barge.duck_ms",
    "voice.barge.stop_ms",
)

# Counters from plan.md OBS-001
VOICE_COUNTERS: tuple[str, ...] = (
    "voice.frames.dropped",
    "voice.ws.reconnects",
    "voice.queue.depth",
    "voice.audio.underruns",
    "voice.generation.stale_drops",
    "voice.sse.dropped",
    "voice.sse.slow_disconnects",
)

# Timeline markers (numeric/IDs only when attached to a turn)
VOICE_EVENTS: tuple[str, ...] = (
    "capture_start",
    "speech_start",
    "speech_end",
    "endpoint_finalized",
    "asr_queued",
    "asr_start",
    "asr_end",
    "transcript_accepted",
    "turn_queued",
    "turn_start",
    "llm_request",
    "llm_first_token",
    "llm_end",
    "first_sentence",
    "tts_queued",
    "tts_start",
    "tts_first_pcm",
    "tts_end",
    "first_audio_sent",
    "first_audio_played_ack",
    "playback_end",
    "barge_onset",
    "barge_duck",
    "barge_confirmed",
    "barge_stopped",
    "barge_restored",
)

# Derived durations: (metric_name, start_event, end_event)
_DURATION_RULES: tuple[tuple[str, str, str], ...] = (
    ("voice.endpoint.ms", "speech_end", "endpoint_finalized"),
    ("voice.asr.queue_ms", "asr_queued", "asr_start"),
    ("voice.asr.ms", "asr_start", "asr_end"),
    ("voice.llm.ttft_ms", "llm_request", "llm_first_token"),
    ("voice.tts.ttfa_ms", "tts_start", "tts_first_pcm"),
    ("voice.e2e.first_audio_ms", "speech_end", "first_audio_sent"),
    ("voice.barge.duck_ms", "barge_onset", "barge_duck"),
    ("voice.barge.stop_ms", "barge_confirmed", "barge_stopped"),
)

_FORBIDDEN_META_KEYS = frozenset(
    {
        "text",
        "transcript",
        "prompt",
        "tokens",
        "audio",
        "pcm",
        "data",
        "secret",
        "password",
        "token",
        "authorization",
        "cookie",
    }
)


def _sanitize_meta(meta: dict[str, Any] | None) -> dict[str, Any]:
    if not meta:
        return {}
    out: dict[str, Any] = {}
    for key, value in meta.items():
        lk = str(key).lower()
        if lk in _FORBIDDEN_META_KEYS or any(f in lk for f in ("secret", "password", "token", "prompt")):
            continue
        if isinstance(value, (str, bytes, bytearray)):
            continue
        if isinstance(value, (int, float, bool)) or value is None:
            out[str(key)] = value
    return out


@dataclass
class VoiceTurnTimeline:
    """Per-turn event timestamps; never stores user/model content."""

    session_id: str = ""
    turn_id: str = ""
    generation_id: int = 0
    correlation_id: str = ""
    marks: dict[str, float] = field(default_factory=dict)

    def mark(self, event: str, *, at: float | None = None) -> None:
        if event not in VOICE_EVENTS:
            raise ValueError(f"unknown voice event: {event}")
        if event in self.marks:
            return
        self.marks[event] = time.perf_counter() if at is None else float(at)

    def duration_ms(self, start: str, end: str) -> float | None:
        if start not in self.marks or end not in self.marks:
            return None
        return max(0.0, (self.marks[end] - self.marks[start]) * 1000.0)

    def flush_durations(self, sink: "VoiceMetrics") -> dict[str, float]:
        recorded: dict[str, float] = {}
        for metric, start, end in _DURATION_RULES:
            ms = self.duration_ms(start, end)
            if ms is None:
                continue
            sink.observe(metric, ms)
            recorded[metric] = ms
        return recorded

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "generation_id": self.generation_id,
            "correlation_id": self.correlation_id,
            "marks": {k: round(v, 6) for k, v in self.marks.items()},
        }


class VoiceMetrics:
    """Process-local voice metrics sink (safe defaults; OTEL export optional later)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._histograms: dict[str, list[float]] = {name: [] for name in VOICE_HISTOGRAMS}
        self._counters: dict[str, int] = {name: 0 for name in VOICE_COUNTERS}
        self._gauge_queue_depth: dict[str, int] = {}
        self._last_meta: dict[str, Any] = {}

    def observe(self, name: str, value_ms: float, *, meta: dict[str, Any] | None = None) -> None:
        if name not in self._histograms:
            raise ValueError(f"unknown voice histogram: {name}")
        clean = _sanitize_meta(meta)
        with self._lock:
            self._histograms[name].append(float(value_ms))
            if clean:
                self._last_meta = clean

    def incr(self, name: str, amount: int = 1, *, meta: dict[str, Any] | None = None) -> None:
        if name not in self._counters:
            raise ValueError(f"unknown voice counter: {name}")
        clean = _sanitize_meta(meta)
        with self._lock:
            self._counters[name] += int(amount)
            if clean:
                self._last_meta = clean

    def set_queue_depth(self, queue_name: str, depth: int) -> None:
        depth_i = max(0, int(depth))
        with self._lock:
            prev = self._gauge_queue_depth.get(queue_name, 0)
            self._gauge_queue_depth[queue_name] = depth_i
            if depth_i > prev:
                # High-water style: counter tracks peak observations via max depth bumps
                self._counters["voice.queue.depth"] = max(
                    self._counters["voice.queue.depth"], depth_i
                )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "histograms": {k: list(v) for k, v in self._histograms.items()},
                "counters": dict(self._counters),
                "queue_depth": dict(self._gauge_queue_depth),
                "last_meta": dict(self._last_meta),
            }

    def reset(self) -> None:
        with self._lock:
            for name in self._histograms:
                self._histograms[name] = []
            for name in self._counters:
                self._counters[name] = 0
            self._gauge_queue_depth.clear()
            self._last_meta.clear()


_METRICS = VoiceMetrics()


def get_voice_metrics() -> VoiceMetrics:
    return _METRICS


def new_turn_timeline(
    *,
    session_id: str = "",
    turn_id: str = "",
    generation_id: int = 0,
    correlation_id: str = "",
) -> VoiceTurnTimeline:
    return VoiceTurnTimeline(
        session_id=str(session_id or ""),
        turn_id=str(turn_id or ""),
        generation_id=int(generation_id or 0),
        correlation_id=str(correlation_id or ""),
    )


def record_stale_generation_drop(*, meta: dict[str, Any] | None = None) -> None:
    get_voice_metrics().incr("voice.generation.stale_drops", meta=meta)


def record_sse_drop() -> None:
    get_voice_metrics().incr("voice.sse.dropped")


def record_sse_slow_disconnect() -> None:
    get_voice_metrics().incr("voice.sse.slow_disconnects")


def record_dropped_mic_frames(n: int = 1) -> None:
    get_voice_metrics().incr("voice.frames.dropped", amount=n)


def record_ws_reconnect() -> None:
    get_voice_metrics().incr("voice.ws.reconnects")


def record_audio_underrun(n: int = 1) -> None:
    get_voice_metrics().incr("voice.audio.underruns", amount=n)


def assert_no_content_keys(payload: dict[str, Any]) -> None:
    """Test helper: fail if a metrics payload looks like it retained user content."""
    banned = _FORBIDDEN_META_KEYS
    for key in payload:
        lk = str(key).lower()
        if lk in banned:
            raise AssertionError(f"metrics payload contains forbidden key: {key}")
    nested = payload.get("last_meta") or {}
    for key in nested:
        lk = str(key).lower()
        if lk in banned or isinstance(nested[key], (str, bytes)):
            raise AssertionError(f"metrics meta leaks content key={key}")


def known_metric_names() -> Iterable[str]:
    return (*VOICE_HISTOGRAMS, *VOICE_COUNTERS)
