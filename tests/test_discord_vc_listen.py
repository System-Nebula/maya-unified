"""Tests for Discord VC listen PCM helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
_VOICE_RUNTIME = _ROOT / "packages" / "voice-runtime"
if str(_VOICE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_VOICE_RUNTIME))

from tools.discord_vc_listen import pcm_stereo_48k_to_mono_16k  # noqa: E402


def test_pcm_stereo_downsample_shape() -> None:
    # 48k stereo, 30 ms → 1440 frames → 2880 samples → 1440 mono → 480 @ 16k
    frames = 1440
    stereo = np.zeros((frames, 2), dtype=np.int16)
    stereo[:, 0] = 1000
    stereo[:, 1] = 2000
    mono = pcm_stereo_48k_to_mono_16k(stereo.tobytes())
    assert mono.dtype == np.int16
    assert mono.shape == (frames // 3,)
    assert int(mono[0]) == 1500


def test_pcm_empty() -> None:
    assert pcm_stereo_48k_to_mono_16k(b"").size == 0


if __name__ == "__main__":
    test_pcm_stereo_downsample_shape()
    test_pcm_empty()
    print("ok")
