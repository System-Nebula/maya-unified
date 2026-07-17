"""Length-prefixed framing for streaming TTS HTTP responses."""

from __future__ import annotations

import io
import json
import struct
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

import numpy as np
import soundfile as sf

_FRAME_PREFIX = struct.Struct("<I")


def pack_meta(meta: dict[str, Any]) -> bytes:
    payload = json.dumps(meta, separators=(",", ":")).encode("utf-8")
    return _FRAME_PREFIX.pack(len(payload)) + payload


def pack_pcm(pcm: bytes) -> bytes:
    return _FRAME_PREFIX.pack(len(pcm)) + pcm


def pack_done(timing: dict[str, Any]) -> bytes:
    payload = json.dumps({"type": "done", **timing}, separators=(",", ":")).encode("utf-8")
    return _FRAME_PREFIX.pack(len(payload)) + payload


def timing_response_headers(
    timing: dict[str, float | int | str],
    *,
    cache: str = "miss",
    cache_key: str = "",
) -> dict[str, str]:
    expose = (
        "X-TTS-Cache, X-TTS-Hash, X-TTS-TTFA-Ms, X-TTS-Synth-Ms, "
        "X-TTS-Encode-Ms, X-TTS-Total-Ms, X-TTS-Lock-Wait-Ms"
    )
    headers = {
        "X-TTS-Cache": cache,
        "X-TTS-Hash": cache_key,
        "Access-Control-Expose-Headers": expose,
    }
    for key, header in (
        ("ttfa_ms", "X-TTS-TTFA-Ms"),
        ("synth_ms", "X-TTS-Synth-Ms"),
        ("encode_ms", "X-TTS-Encode-Ms"),
        ("total_ms", "X-TTS-Total-Ms"),
        ("lock_wait_ms", "X-TTS-Lock-Wait-Ms"),
    ):
        val = timing.get(key)
        if val is not None:
            headers[header] = str(int(round(float(val))))
    return headers


@dataclass
class TtsStreamEncoder:
    cache_key: str
    _t0: float = field(default_factory=time.perf_counter)
    _sr: int = 24000
    _meta_sent: bool = False
    _pcm_parts: list[np.ndarray] = field(default_factory=list)
    _ttfa_ms: float = 0.0
    _engine_prefill_ms: float = 0.0
    _engine_decode_ms: float = 0.0
    _lock_wait_ms: float = 0.0
    wav_bytes: bytes | None = None
    timing: dict[str, float] = field(default_factory=dict)

    def frames(
        self, chunks: Iterator[tuple[bytes, int, bool, dict[str, Any]]]
    ) -> Iterator[bytes]:
        for pcm_bytes, sample_rate, is_first, engine_timing in chunks:
            self._sr = sample_rate
            self._pcm_parts.append(np.frombuffer(pcm_bytes, dtype=np.float32))
            if is_first:
                self._ttfa_ms = (time.perf_counter() - self._t0) * 1000.0
                self._engine_prefill_ms = float(engine_timing.get("prefill_ms") or 0)
                self._engine_decode_ms = float(engine_timing.get("decode_ms") or 0)
                self._lock_wait_ms = float(engine_timing.get("lock_wait_ms") or 0)
                try:
                    from services.voice.metrics import get_voice_metrics

                    get_voice_metrics().observe("voice.tts.ttfa_ms", self._ttfa_ms)
                except Exception:
                    pass
                if not self._meta_sent:
                    yield pack_meta(
                        {
                            "format": "f32le",
                            "sr": self._sr,
                            "channels": 1,
                            "hash": self.cache_key,
                        }
                    )
                    self._meta_sent = True
            yield pack_pcm(pcm_bytes)

        synth_ms = (time.perf_counter() - self._t0) * 1000.0
        encode_ms = 0.0
        if self._pcm_parts:
            t_enc = time.perf_counter()
            audio = np.concatenate(self._pcm_parts)
            buf = io.BytesIO()
            sf.write(buf, audio, self._sr, format="WAV", subtype="PCM_16")
            self.wav_bytes = buf.getvalue()
            encode_ms = (time.perf_counter() - t_enc) * 1000.0

        self.timing = {
            "ttfa_ms": self._ttfa_ms,
            "synth_ms": synth_ms,
            "encode_ms": encode_ms,
            "total_ms": synth_ms,
            "lock_wait_ms": self._lock_wait_ms,
            "engine_prefill_ms": self._engine_prefill_ms,
            "engine_decode_ms": self._engine_decode_ms,
        }
        yield pack_done(self.timing)
