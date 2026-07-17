"""PRE-001 duplex baseline result schema."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


SCHEMA_VERSION = 1

# Latency fields from plan.md PRE-001 (milliseconds). None = not measured.
LATENCY_FIELDS = (
    "speech_end_to_finalized_ms",
    "asr_duration_ms",
    "transcript_to_llm_first_token_ms",
    "llm_first_token_to_tts_request_ms",
    "tts_request_to_first_pcm_ms",
    "speech_end_to_first_audible_pcm_ms",
    "barge_onset_to_duck_ms",
    "barge_confirm_to_silence_ms",
    "event_loop_lag_ms",
)


@dataclass
class BaselineInput:
    sample_rate: int = 48000
    chunk_ms: float = 20.0
    fixture: str = "stub"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BaselineSample:
    cold: bool
    speech_end_to_finalized_ms: float | None = None
    asr_duration_ms: float | None = None
    transcript_to_llm_first_token_ms: float | None = None
    llm_first_token_to_tts_request_ms: float | None = None
    tts_request_to_first_pcm_ms: float | None = None
    speech_end_to_first_audible_pcm_ms: float | None = None
    barge_onset_to_duck_ms: float | None = None
    barge_confirm_to_silence_ms: float | None = None
    event_loop_lag_ms: float | None = None
    underruns: int = 0
    dropped_mic_frames: int = 0
    ws_reconnects: int = 0
    queue_high_water: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BaselineCounters:
    underruns: int = 0
    dropped_mic_frames: int = 0
    ws_reconnects: int = 0
    event_loop_lag_ms_max: float = 0.0
    queue_high_water: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def empty_latency_dict() -> dict[str, float | None]:
    return {name: None for name in LATENCY_FIELDS}
