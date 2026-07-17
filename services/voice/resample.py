"""High-quality mono resampling via torchaudio (AUDIO-004).

Replaces naive every-Nth-sample decimation and sample-repeat upsampling.
"""

from __future__ import annotations

import numpy as np

try:
    import torch
    from torchaudio.functional import resample as _torch_resample
except Exception:  # noqa: BLE001
    torch = None  # type: ignore[assignment]
    _torch_resample = None  # type: ignore[assignment]


def resample_float32_mono(
    samples: np.ndarray,
    src_rate: int,
    dst_rate: int,
) -> np.ndarray:
    """Resample mono float32 PCM. Prefers torchaudio; falls back to linear interp."""
    if samples.size == 0 or src_rate == dst_rate:
        return np.asarray(samples, dtype=np.float32).reshape(-1)
    src_rate = int(src_rate)
    dst_rate = int(dst_rate)
    if src_rate <= 0 or dst_rate <= 0:
        raise ValueError("invalid sample rate")
    x = np.ascontiguousarray(samples, dtype=np.float32).reshape(-1)
    if _torch_resample is not None and torch is not None:
        t = torch.from_numpy(x)
        out = _torch_resample(t, src_rate, dst_rate)
        return out.detach().cpu().numpy().astype(np.float32, copy=False)
    # Fallback: linear interpolation (better than ::N, weaker anti-alias than sinc).
    duration = x.size / float(src_rate)
    dst_n = max(1, int(round(duration * dst_rate)))
    t_old = np.linspace(0.0, 1.0, x.size, endpoint=False)
    t_new = np.linspace(0.0, 1.0, dst_n, endpoint=False)
    return np.interp(t_new, t_old, x).astype(np.float32)


def resample_s16le_mono(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Resample mono s16le bytes between arbitrary rates."""
    if not pcm or src_rate == dst_rate:
        return pcm
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    out = resample_float32_mono(samples, src_rate, dst_rate)
    return np.clip(out * 32767.0, -32768, 32767).astype("<i2").tobytes()


def downsample_mono_48k_to_16k_int16(pcm_mono_48k: bytes) -> np.ndarray:
    """48 kHz mono s16le → 16 kHz mono int16 (anti-aliased)."""
    if not pcm_mono_48k:
        return np.zeros(0, dtype=np.int16)
    samples = np.frombuffer(pcm_mono_48k, dtype="<i2").astype(np.float32) / 32768.0
    out = resample_float32_mono(samples, 48000, 16000)
    return np.clip(out * 32767.0, -32768, 32767).astype(np.int16)


def upsample_mono_16k_to_48k_int16(pcm_mono_16k: np.ndarray | bytes) -> np.ndarray:
    """16 kHz mono int16 → 48 kHz mono int16 (band-limited upsample)."""
    if isinstance(pcm_mono_16k, (bytes, bytearray)):
        if not pcm_mono_16k:
            return np.zeros(0, dtype=np.int16)
        samples = np.frombuffer(pcm_mono_16k, dtype="<i2").astype(np.float32) / 32768.0
    else:
        arr = np.asarray(pcm_mono_16k, dtype=np.int16).reshape(-1)
        if arr.size == 0:
            return np.zeros(0, dtype=np.int16)
        samples = arr.astype(np.float32) / 32768.0
    out = resample_float32_mono(samples, 16000, 48000)
    return np.clip(out * 32767.0, -32768, 32767).astype(np.int16)


def naive_decimate_48k_to_16k(pcm_mono_48k: bytes) -> np.ndarray:
    """Legacy every-third-sample path — kept for golden alias-rejection tests."""
    if not pcm_mono_48k:
        return np.zeros(0, dtype=np.int16)
    mono = np.frombuffer(pcm_mono_48k, dtype="<i2")
    return mono[::3].astype(np.int16)
