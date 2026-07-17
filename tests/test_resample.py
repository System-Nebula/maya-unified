"""AUDIO-004: anti-aliased resampling golden tests."""

from __future__ import annotations

import time

import numpy as np

from services.voice.resample import (
    downsample_mono_48k_to_16k_int16,
    naive_decimate_48k_to_16k,
    resample_float32_mono,
    resample_s16le_mono,
    upsample_mono_16k_to_48k_int16,
)


def _sine_s16le(freq_hz: float, duration_s: float, rate: int, amp: float = 0.5) -> bytes:
    n = int(rate * duration_s)
    t = np.arange(n, dtype=np.float64) / rate
    wave = amp * np.sin(2.0 * np.pi * freq_hz * t)
    return np.clip(wave * 32767.0, -32768, 32767).astype("<i2").tobytes()


def _rms(x: np.ndarray) -> float:
    if x.size == 0:
        return 0.0
    f = x.astype(np.float64) / 32768.0
    return float(np.sqrt(np.mean(f * f)))


def test_in_band_sine_amplitude_preserved() -> None:
    # 1 kHz is well below Nyquist at 16 kHz.
    pcm48 = _sine_s16le(1000.0, 0.25, 48000, amp=0.4)
    out = downsample_mono_48k_to_16k_int16(pcm48)
    assert abs(out.size - int(16000 * 0.25)) <= 2
    in_rms = _rms(np.frombuffer(pcm48, dtype="<i2"))
    out_rms = _rms(out)
    # Amplitude should stay within ~25% of input RMS.
    assert abs(out_rms - in_rms) / max(in_rms, 1e-9) < 0.25


def test_out_of_band_alias_rejection_vs_naive() -> None:
    # 12 kHz at 48 kHz aliases to 4 kHz under ::3 decimation; proper resample rejects it.
    pcm48 = _sine_s16le(12000.0, 0.5, 48000, amp=0.6)
    good = downsample_mono_48k_to_16k_int16(pcm48)
    naive = naive_decimate_48k_to_16k(pcm48)
    assert _rms(good) < 0.35 * _rms(naive)
    assert _rms(good) < 0.08  # near silence after anti-alias


def test_no_clipping_or_dc_offset() -> None:
    pcm48 = _sine_s16le(440.0, 0.2, 48000, amp=0.9)
    out = downsample_mono_48k_to_16k_int16(pcm48)
    assert int(out.min()) > -32768
    assert int(out.max()) < 32767
    dc = float(np.mean(out.astype(np.float64)))
    assert abs(dc) < 50.0  # negligible DC on s16 scale


def test_upsample_16k_to_48k_duration() -> None:
    pcm16 = np.frombuffer(_sine_s16le(800.0, 0.1, 16000), dtype="<i2")
    up = upsample_mono_16k_to_48k_int16(pcm16)
    assert abs(up.size - int(48000 * 0.1)) <= 2


def test_44100_to_48000_s16le() -> None:
    pcm = _sine_s16le(500.0, 0.05, 44100)
    out = resample_s16le_mono(pcm, 44100, 48000)
    n_out = len(out) // 2
    assert abs(n_out - int(48000 * 0.05)) <= 2


def test_speech_like_snr_beats_naive() -> None:
    """In-band tone + out-of-band interferer: good resample keeps higher SNR."""
    rate = 48000
    n = rate // 2
    t = np.arange(n, dtype=np.float64) / rate
    speech = 0.35 * np.sin(2.0 * np.pi * 700.0 * t)
    interferer = 0.45 * np.sin(2.0 * np.pi * 11000.0 * t)
    mix = np.clip((speech + interferer) * 32767.0, -32768, 32767).astype("<i2").tobytes()
    good = downsample_mono_48k_to_16k_int16(mix).astype(np.float64) / 32768.0
    naive = naive_decimate_48k_to_16k(mix).astype(np.float64) / 32768.0
    # Correlate against a 700 Hz reference at 16 kHz.
    t16 = np.arange(good.size, dtype=np.float64) / 16000.0
    ref = np.sin(2.0 * np.pi * 700.0 * t16)
    # Align lengths
    m = min(good.size, naive.size, ref.size)
    good, naive, ref = good[:m], naive[:m], ref[:m]

    def snr(sig: np.ndarray) -> float:
        # Project onto ref; residual is noise/alias.
        coef = float(np.dot(sig, ref) / max(np.dot(ref, ref), 1e-12))
        clean = coef * ref
        noise = sig - clean
        return 10.0 * np.log10(max(np.mean(clean * clean), 1e-12) / max(np.mean(noise * noise), 1e-12))

    assert snr(good) > snr(naive) + 3.0


def test_warm_resample_latency_gate() -> None:
    """1 s of 48 kHz mono should resample well under a warm-turn budget."""
    pcm = _sine_s16le(1000.0, 1.0, 48000)
    # Warm-up
    downsample_mono_48k_to_16k_int16(pcm[:9600])
    t0 = time.perf_counter()
    downsample_mono_48k_to_16k_int16(pcm)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert elapsed_ms < 250.0, f"resample took {elapsed_ms:.1f}ms"


def test_float_identity_rate() -> None:
    x = np.linspace(-0.5, 0.5, 100, dtype=np.float32)
    y = resample_float32_mono(x, 16000, 16000)
    np.testing.assert_array_equal(y, x)
