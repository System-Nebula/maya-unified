"""Shared duplex mic ingress — sample-time RMS VAD, HushMic 48 kHz, utterance finalize."""

from __future__ import annotations

import io
import wave
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

import numpy as np

BROWSER_INPUT_SAMPLE_RATE = 48000
BARGE_ONSET_MS = 180.0
PREROLL_MS = 200.0
START_HYSTERESIS_MS = 60.0
NOISE_FLOOR_ALPHA = 0.05
NOISE_FLOOR_MULT = 2.5


def pcm16_bytes_to_float32(data: bytes) -> np.ndarray:
    samples = np.frombuffer(data, dtype="<i2")
    return samples.astype(np.float32) / 32768.0


def rms_float_pcm(data: bytes) -> float:
    """RMS on normalized float PCM (0.0–1.0 scale)."""
    samples = pcm16_bytes_to_float32(data)
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples), dtype=np.float64)))


def pcm16_to_wav(data: bytes, sample_rate: int = 16000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(data)
    return output.getvalue()


def ms_to_samples(ms: float, sample_rate: int = BROWSER_INPUT_SAMPLE_RATE) -> int:
    return max(0, int(round(float(ms) * sample_rate / 1000.0)))


def samples_to_ms(samples: int, sample_rate: int = BROWSER_INPUT_SAMPLE_RATE) -> float:
    if sample_rate <= 0:
        return 0.0
    return samples * 1000.0 / float(sample_rate)


def _vad_config() -> Any:
    from config import CONFIG

    return CONFIG.vad


def _audio_config() -> Any:
    from config import CONFIG

    return CONFIG.audio


def _barge_mode() -> str:
    try:
        return str(getattr(_audio_config(), "barge_mode", "smart") or "smart").lower()
    except Exception:  # noqa: BLE001
        return "smart"


class ChunkSignal(Enum):
    NONE = auto()
    DUCK = auto()
    INTERRUPT = auto()  # instant barge: stop matching playback generation
    FINALIZE = auto()


@dataclass
class DuplexIngressSession:
    recording: bytearray = field(default_factory=bytearray)
    samples_seen: int = 0
    speech_start_sample: int | None = None
    last_voice_sample: int | None = None
    sustained_voice_samples: int = 0
    preroll: deque[bytes] = field(default_factory=deque)
    preroll_samples: int = 0
    noise_floor: float = 0.0
    noise_samples: int = 0
    assistant_speaking: bool = False
    barge_in_candidate: bool = False
    duck_sent: bool = False

    def reset_turn_state(self) -> None:
        self.recording.clear()
        self.speech_start_sample = None
        self.last_voice_sample = None
        self.sustained_voice_samples = 0
        self.preroll.clear()
        self.preroll_samples = 0
        self.barge_in_candidate = False
        self.duck_sent = False
        # Keep samples_seen + noise_floor across turns (timeline continuity).

    def reset_on_gap(self) -> None:
        """Sequence gap: drop endpointing state so silence math stays coherent."""
        self.reset_turn_state()
        self.samples_seen = 0

    def set_assistant_speaking(self, speaking: bool) -> None:
        self.assistant_speaking = bool(speaking)
        if not speaking:
            self.duck_sent = False
            self.barge_in_candidate = False
            self.sustained_voice_samples = 0


def enhance_pcm48_mono(
    pcm48: bytes,
    *,
    user_id: int = 0,
    enhancer_key: Any | None = None,
) -> bytes:
    """HushMic enhance a full mono 48 kHz utterance."""
    if not pcm48:
        return b""
    audio = _audio_config()
    if not audio.hushmic_enabled:
        return pcm48
    try:
        from services.voice.hushmic import get_hushmic_processor

        kwargs: dict[str, Any] = {}
        if enhancer_key is not None:
            kwargs["key"] = enhancer_key
        else:
            kwargs["user_id"] = user_id
        return get_hushmic_processor().enhance_mono_utterance(pcm48, **kwargs)
    except Exception:  # noqa: BLE001
        return pcm48


def process_stream_chunk(
    pcm48: bytes,
    *,
    user_id: int = 0,
    enhancer_key: Any | None = None,
) -> bytes:
    """Streaming HushMic pass for one browser mic chunk."""
    if not pcm48:
        return b""
    audio = _audio_config()
    if not audio.hushmic_enabled:
        return pcm48
    try:
        from services.voice.hushmic import get_hushmic_processor

        kwargs: dict[str, Any] = {}
        if enhancer_key is not None:
            kwargs["key"] = enhancer_key
        else:
            kwargs["user_id"] = user_id
        return get_hushmic_processor().process_mono_48k(pcm48, **kwargs)
    except Exception:  # noqa: BLE001
        return pcm48


def utterance_pcm48_to_int16_16k(pcm48: bytes, *, user_id: int = 0) -> np.ndarray:
    """Downsample a browser utterance already enhanced during streaming.

    ``ingest_pcm_chunk`` stores the output of ``process_stream_chunk``. Running
    the full recording through HushMic again here applies the denoiser twice,
    which can damage speech and adds avoidable latency before ASR.
    """
    from services.voice.hushmic import downsample_mono_48k_to_16k_int16

    if not pcm48:
        return np.zeros(0, dtype=np.int16)
    return downsample_mono_48k_to_16k_int16(pcm48)


def _effective_threshold(session: DuplexIngressSession, vad: Any) -> float:
    base = float(getattr(vad, "rms_threshold", 0.015) or 0.015)
    if session.noise_samples <= 0:
        return base
    return max(base, session.noise_floor * NOISE_FLOOR_MULT)


def _update_noise_floor(session: DuplexIngressSession, level: float, n_samples: int) -> None:
    if n_samples <= 0:
        return
    if session.noise_samples == 0:
        session.noise_floor = level
        session.noise_samples = n_samples
        return
    session.noise_floor = (1.0 - NOISE_FLOOR_ALPHA) * session.noise_floor + NOISE_FLOOR_ALPHA * level
    session.noise_samples += n_samples


def _push_preroll(session: DuplexIngressSession, chunk: bytes, n_samples: int, max_samples: int) -> None:
    if n_samples <= 0 or max_samples <= 0:
        return
    session.preroll.append(chunk)
    session.preroll_samples += n_samples
    while session.preroll and session.preroll_samples > max_samples:
        old = session.preroll.popleft()
        session.preroll_samples -= len(old) // 2


def _flush_preroll(session: DuplexIngressSession) -> None:
    if not session.preroll:
        return
    for piece in session.preroll:
        session.recording.extend(piece)
    session.preroll.clear()
    session.preroll_samples = 0


def _begin_speech(session: DuplexIngressSession, chunk: bytes, chunk_end: int) -> None:
    preroll_samples = session.preroll_samples
    _flush_preroll(session)
    n = len(chunk) // 2
    session.speech_start_sample = max(0, chunk_end - n - preroll_samples)
    session.last_voice_sample = chunk_end
    session.recording.extend(chunk)


def ingest_pcm_chunk(
    session: DuplexIngressSession,
    raw_pcm48: bytes,
    *,
    now: float | None = None,  # noqa: ARG001 — kept for call-site compat; unused (sample-time)
    user_id: int = 0,
    enhancer_key: Any | None = None,
    barge_onset_ms: float = BARGE_ONSET_MS,
    barge_mode: str | None = None,
    sample_rate: int = BROWSER_INPUT_SAMPLE_RATE,
) -> tuple[ChunkSignal, bytes | None]:
    """
    Process one browser mic chunk using sample-time endpointing.

    Silence, min speech, max turn, and barge onset are derived from sample
    indices so backlogged frame processing matches real-time results.
    """
    del now  # wall-clock must not drive endpointing
    vad = _vad_config()
    chunk = process_stream_chunk(raw_pcm48, user_id=user_id, enhancer_key=enhancer_key)
    if not chunk:
        return ChunkSignal.NONE, None

    n_samples = len(chunk) // 2
    if n_samples <= 0:
        return ChunkSignal.NONE, None

    chunk_end = session.samples_seen + n_samples
    session.samples_seen = chunk_end

    level = rms_float_pcm(chunk)
    threshold = _effective_threshold(session, vad)
    voiced = level >= threshold

    silence_need = ms_to_samples(float(getattr(vad, "silence_ms", 650)), sample_rate)
    max_turn = ms_to_samples(float(getattr(vad, "max_turn_ms", 30000)), sample_rate)
    start_hyst = ms_to_samples(
        float(getattr(vad, "start_hysteresis_ms", START_HYSTERESIS_MS)),
        sample_rate,
    )
    preroll_max = ms_to_samples(
        float(getattr(vad, "preroll_ms", PREROLL_MS)),
        sample_rate,
    )
    barge_need = ms_to_samples(float(barge_onset_ms), sample_rate)
    mode = (barge_mode if barge_mode is not None else _barge_mode()).lower()

    # Ignore mic growth while assistant speaks and barge is off.
    if session.assistant_speaking and mode == "off":
        if not voiced:
            _update_noise_floor(session, level, n_samples)
        return ChunkSignal.NONE, None

    if voiced:
        session.sustained_voice_samples += n_samples

        if session.speech_start_sample is None:
            if session.sustained_voice_samples < max(1, start_hyst):
                # Hold in preroll until hysteresis commits speech.
                _push_preroll(session, chunk, n_samples, preroll_max)
                return ChunkSignal.NONE, None
            _begin_speech(session, chunk, chunk_end)
        else:
            session.last_voice_sample = chunk_end
            session.recording.extend(chunk)

        signal = ChunkSignal.NONE
        if session.assistant_speaking and mode != "off":
            session.barge_in_candidate = True
            if session.sustained_voice_samples >= max(1, barge_need) and not session.duck_sent:
                session.duck_sent = True
                if mode == "instant":
                    signal = ChunkSignal.INTERRUPT
                else:
                    signal = ChunkSignal.DUCK

        if (
            session.speech_start_sample is not None
            and max_turn > 0
            and (chunk_end - session.speech_start_sample) >= max_turn
        ):
            pcm = take_finalized_utterance(session, sample_rate=sample_rate)
            if pcm is not None:
                return ChunkSignal.FINALIZE, pcm
            return signal, None

        return signal, None

    # Unvoiced frame — break sustained barge onset (silence between voiced bursts).
    session.sustained_voice_samples = 0

    if session.speech_start_sample is None:
        _update_noise_floor(session, level, n_samples)
        _push_preroll(session, chunk, n_samples, preroll_max)
        return ChunkSignal.NONE, None

    session.recording.extend(chunk)
    if session.last_voice_sample is not None:
        silence_samples = chunk_end - session.last_voice_sample
        hit_silence = silence_samples >= max(1, silence_need)
        hit_max = max_turn > 0 and (chunk_end - session.speech_start_sample) >= max_turn
        if hit_silence or hit_max:
            pcm = take_finalized_utterance(session, sample_rate=sample_rate)
            if pcm is not None:
                return ChunkSignal.FINALIZE, pcm

    return ChunkSignal.NONE, None


def take_finalized_utterance(
    session: DuplexIngressSession,
    *,
    sample_rate: int = BROWSER_INPUT_SAMPLE_RATE,
) -> bytes | None:
    """Extract and clear recording if it meets min duration; else reset."""
    if not session.recording:
        session.reset_turn_state()
        return None

    pcm = bytes(session.recording)
    session.reset_turn_state()

    vad = _vad_config()
    duration_ms = samples_to_ms(len(pcm) // 2, sample_rate)
    if duration_ms < float(getattr(vad, "min_speech_ms", 0) or 0):
        return None
    return pcm


def discord_stereo_utterance_to_int16_16k(
    pcm_stereo: bytes,
    *,
    user_id: int,
    guild_id: int | str | None = None,
) -> np.ndarray:
    """Enhance Discord stereo utterance and downsample to 16 kHz mono for STT."""
    from services.voice.hushmic import (
        discord_key,
        downsample_mono_48k_to_16k_int16,
        get_hushmic_processor,
        stereo_48k_to_mono_48k_bytes,
    )

    if not pcm_stereo:
        return np.zeros(0, dtype=np.int16)
    audio = _audio_config()
    key = discord_key(user_id, guild_id=guild_id)
    if audio.hushmic_enabled:
        try:
            mono_48k = get_hushmic_processor().enhance_discord_utterance(
                pcm_stereo,
                user_id=user_id,
                guild_id=guild_id,
                key=key,
            )
            if mono_48k:
                return downsample_mono_48k_to_16k_int16(mono_48k)
        except Exception:  # noqa: BLE001
            pass
    mono_48k = stereo_48k_to_mono_48k_bytes(pcm_stereo)
    if not mono_48k:
        return np.zeros(0, dtype=np.int16)
    return downsample_mono_48k_to_16k_int16(mono_48k)


def reset_hushmic_stream(key: Any | None = None) -> None:
    try:
        from services.voice.hushmic import get_hushmic_processor

        get_hushmic_processor().reset(key)
    except Exception:  # noqa: BLE001
        pass
