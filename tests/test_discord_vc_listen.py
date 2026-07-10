"""Tests for Discord VC listen PCM helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
_VOICE_RUNTIME = _ROOT / "packages" / "voice-runtime"
if str(_VOICE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_VOICE_RUNTIME))

from tools.discord_vc_listen import (  # noqa: E402
    _extract_pcm_and_user,
    pcm_stereo_48k_to_mono_16k,
)


def test_pcm_stereo_downsample_shape() -> None:
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


def test_extract_voice_data() -> None:
    member = SimpleNamespace(id=42)
    data = SimpleNamespace(pcm=b"\x01\x00\x02\x00", source=member)
    pcm, uid = _extract_pcm_and_user(data, member)
    assert pcm == b"\x01\x00\x02\x00"
    assert uid == 42


def test_extract_legacy_bytes() -> None:
    pcm, uid = _extract_pcm_and_user(b"\x03\x00", 99)
    assert pcm == b"\x03\x00"
    assert uid == 99


if __name__ == "__main__":
    test_pcm_stereo_downsample_shape()
    test_pcm_empty()
    test_extract_voice_data()
    test_extract_legacy_bytes()
    print("ok")
