#!/usr/bin/env python3
"""Smoke-test Qwen3 TTS: load model, synthesize a short phrase, report RTF and TTFA."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "voice-runtime"))

# Custom mode avoids needing a reference clip for smoke tests.
os.environ.setdefault("VA_TTS_MODE", "custom")


def main() -> int:
    parser = argparse.ArgumentParser(description="Qwen3 TTS smoke test")
    parser.add_argument(
        "--clone",
        action="store_true",
        help="Use clone mode (requires VA_TTS_REF_AUDIO reference clip)",
    )
    parser.add_argument("--text", default="TTS smoke test.", help="Phrase to synthesize")
    args = parser.parse_args()

    if args.clone:
        os.environ["VA_TTS_MODE"] = "clone"

    from config import CONFIG  # noqa: E402
    from tts import load_tts  # noqa: E402

    print(f"[check_tts] device={CONFIG.tts.device} mode={CONFIG.tts.mode}")
    voice = load_tts()
    if not getattr(voice, "available", False):
        print(f"[check_tts] FAIL: TTS unavailable — {getattr(voice, 'degrade_reason', 'unknown')}")
        return 1

    text = args.text
    t0 = time.perf_counter()
    ttfa: float | None = None
    chunks = 0
    samples = 0
    sr = 0
    prefill_ms = 0.0
    decode_ms = 0.0
    stream_fn = getattr(voice, "stream_timed", voice.stream)
    for i, item in enumerate(stream_fn(text)):
        if i == 0:
            ttfa = time.perf_counter() - t0
        if len(item) == 3:
            audio, sample_rate, timing = item
            if i == 0 and timing:
                prefill_ms = float(timing.get("prefill_ms") or 0)
                decode_ms = float(timing.get("decode_ms") or 0)
        else:
            audio, sample_rate = item
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
    if ttfa is not None:
        print(
            f"[check_tts] TTFA={ttfa:.3f}s engine_prefill_ms={prefill_ms:.0f} "
            f"engine_decode_ms={decode_ms:.0f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
