#!/usr/bin/env python3
"""Smoke-test Qwen3 TTS: load model, synthesize a short phrase, report RTF."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "voice-runtime"))

# Custom mode avoids needing a reference clip for smoke tests.
os.environ.setdefault("VA_TTS_MODE", "custom")

from config import CONFIG  # noqa: E402
from tts import load_tts  # noqa: E402


def main() -> int:
    print(f"[check_tts] device={CONFIG.tts.device} mode={CONFIG.tts.mode}")
    voice = load_tts()
    if not getattr(voice, "available", False):
        print(f"[check_tts] FAIL: TTS unavailable — {getattr(voice, 'degrade_reason', 'unknown')}")
        return 1

    text = "TTS smoke test."
    t0 = time.perf_counter()
    chunks = 0
    samples = 0
    sr = 0
    for audio, sample_rate in voice.stream(text):
        chunks += 1
        samples += len(audio)
        sr = sample_rate
    elapsed = time.perf_counter() - t0
    if chunks == 0 or sr == 0:
        print("[check_tts] FAIL: no audio produced")
        return 1

    audio_sec = samples / sr
    rtf = audio_sec / elapsed if elapsed > 0 else 0.0
    print(
        f"[check_tts] OK: {chunks} chunk(s), {audio_sec:.2f}s audio in {elapsed:.2f}s "
        f"(RTF={rtf:.2f}, sr={sr})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
