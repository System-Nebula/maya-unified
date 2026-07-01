"""Speech-to-text via faster-whisper.

Exposes a single `transcribe_array(int16_audio, sample_rate) -> str` used by the
mic-driven modes (push-to-talk and VAD).
"""

from __future__ import annotations

import os
import tempfile
import wave

import numpy as np

from config import CONFIG, STTConfig


def _write_temp_wav(audio_int16: np.ndarray, sample_rate: int) -> str:
    audio_int16 = np.asarray(audio_int16, dtype=np.int16).reshape(-1)
    fd = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    path = fd.name
    fd.close()
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())
    return path


class WhisperSTT:
    def __init__(self, cfg: STTConfig | None = None):
        self.cfg = cfg or CONFIG.stt
        from faster_whisper import WhisperModel

        device = "cuda" if self.cfg.device.startswith("cuda") else self.cfg.device
        compute_type = self.cfg.whisper_compute_type
        if device == "cpu" and compute_type == "float16":
            compute_type = "int8"  # float16 is not supported on CPU
        self.model = WhisperModel(
            self.cfg.whisper_model,
            device=device,
            compute_type=compute_type,
        )

    def transcribe_file(self, path: str, *, barge: bool = False) -> str:
        kwargs: dict = {
            "language": self.cfg.language or None,
            "beam_size": 1,
            "vad_filter": barge,
        }
        if barge:
            kwargs.update(
                no_speech_threshold=0.62,
                log_prob_threshold=-0.45,
                compression_ratio_threshold=2.2,
                condition_on_previous_text=False,
            )
        segments, _info = self.model.transcribe(path, **kwargs)
        return " ".join(seg.text.strip() for seg in segments).strip()

    def transcribe_array(
        self,
        audio_int16: np.ndarray,
        sample_rate: int | None = None,
        *,
        barge: bool = False,
    ) -> str:
        sr = sample_rate or self.cfg.sample_rate
        path = _write_temp_wav(audio_int16, sr)
        try:
            return self.transcribe_file(path, barge=barge)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


def create_stt(cfg: STTConfig | None = None) -> WhisperSTT:
    return WhisperSTT(cfg)
