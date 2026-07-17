"""Quick STT latency comparison: Qwen3-ASR HTTP vs faster-whisper."""

from __future__ import annotations

import io
import sys
import time
import wave
from pathlib import Path

import httpx
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "packages" / "voice-runtime"
sys.path.insert(0, str(RUNTIME))

sr = 16000
dur = 2.5
rng = np.random.default_rng(0)
audio = (rng.standard_normal(int(sr * dur)) * 8000).astype(np.int16)


def make_wav(pcm: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


wav = make_wav(audio)

print("=== Qwen3-ASR (HTTP :8091) ===")
for i in range(3):
    t = time.perf_counter()
    r = httpx.post(
        "http://127.0.0.1:8091/v1/audio/transcriptions",
        data={"model": "Qwen/Qwen3-ASR-0.6B", "language": "English"},
        files={"file": ("t.wav", wav, "application/octet-stream")},
        timeout=120,
    )
    r.raise_for_status()
    text = str(r.json().get("text", ""))[:50]
    print(f"  run {i + 1}: {(time.perf_counter() - t) * 1000:.0f} ms  text={text!r}")

print("=== faster-whisper (local GPU) ===")
try:
    from config import CONFIG
    from stt import WhisperSTT, _write_temp_wav

    cfg = CONFIG.stt
    cfg.backend = "whisper"
    cfg.whisper_model = "small.en"
    w = WhisperSTT(cfg)
    path = _write_temp_wav(audio, sr)
    for i in range(3):
        t = time.perf_counter()
        text = w.transcribe_file(path)
        print(f"  run {i + 1}: {(time.perf_counter() - t) * 1000:.0f} ms  text={text[:50]!r}")
except Exception as exc:
    print(f"  skipped: {exc}")
