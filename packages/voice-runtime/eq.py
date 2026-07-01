"""Live output EQ for streaming TTS playback.

Runs in the audio callback thread as a chain of biquad IIR filters (RBJ cookbook).
Presets reshape the *played* voice without re-generating TTS.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Any

import numpy as np

# Preset id -> human label (UI).
EQ_PRESET_LABELS: dict[str, str] = {
    "off": "Off (bypass)",
    "flat": "Flat",
    "radio": "Radio",
    "speaker": "Small speaker",
    "telephone": "Telephone",
    "warm": "Warm",
    "bright": "Bright",
    "bass": "Bass boost",
    "studio": "Studio",
    "custom": "Custom",
}

# UI node colors (FabFilter-ish palette).
EQ_BAND_COLORS = ("#8b5cf6", "#a78bfa", "#7c3aed", "#c084fc", "#6366f1", "#a855f7", "#d8b4fe")

# Each preset is a list of filter specs applied in order.
# Types: highpass, lowpass, peak, low_shelf, high_shelf
EQ_PRESETS: dict[str, list[dict[str, Any]]] = {
    "off": [],
    "flat": [],
    "radio": [
        {"type": "highpass", "freq": 350, "q": 0.71},
        {"type": "peak", "freq": 2800, "gain_db": 4.0, "q": 1.1},
        {"type": "peak", "freq": 5200, "gain_db": 2.0, "q": 0.9},
        {"type": "lowpass", "freq": 9000, "q": 0.71},
    ],
    "speaker": [
        {"type": "highpass", "freq": 110, "q": 0.71},
        {"type": "low_shelf", "freq": 220, "gain_db": 3.5, "q": 0.7},
        {"type": "peak", "freq": 2600, "gain_db": 2.5, "q": 1.0},
        {"type": "high_shelf", "freq": 6500, "gain_db": -5.0, "q": 0.7},
    ],
    "telephone": [
        {"type": "highpass", "freq": 320, "q": 0.8},
        {"type": "peak", "freq": 1100, "gain_db": 2.5, "q": 0.9},
        {"type": "lowpass", "freq": 3400, "q": 0.8},
    ],
    "warm": [
        {"type": "low_shelf", "freq": 250, "gain_db": 3.0, "q": 0.7},
        {"type": "peak", "freq": 3500, "gain_db": -1.5, "q": 0.8},
        {"type": "high_shelf", "freq": 8000, "gain_db": -3.5, "q": 0.7},
    ],
    "bright": [
        {"type": "high_shelf", "freq": 4000, "gain_db": 4.0, "q": 0.7},
        {"type": "peak", "freq": 9000, "gain_db": 2.0, "q": 0.8},
    ],
    "bass": [
        {"type": "low_shelf", "freq": 180, "gain_db": 6.0, "q": 0.7},
        {"type": "peak", "freq": 90, "gain_db": 3.0, "q": 0.9},
    ],
    "studio": [
        {"type": "highpass", "freq": 80, "q": 0.71},
        {"type": "peak", "freq": 3200, "gain_db": 1.5, "q": 0.9},
        {"type": "high_shelf", "freq": 10000, "gain_db": 1.0, "q": 0.7},
    ],
}


def list_eq_presets() -> list[dict[str, str]]:
    return [{"id": k, "label": EQ_PRESET_LABELS.get(k, k.title())} for k in EQ_PRESET_LABELS]


def get_preset_bands(preset: str) -> list[dict[str, Any]]:
    """Return the filter bands for a preset, annotated for the EQ UI."""
    specs = EQ_PRESETS.get((preset or "off").lower(), [])
    out: list[dict[str, Any]] = []
    for i, spec in enumerate(specs):
        band = dict(spec)
        band["id"] = i
        band["color"] = EQ_BAND_COLORS[i % len(EQ_BAND_COLORS)]
        if band["type"] in ("highpass", "lowpass") and "gain_db" not in band:
            band["gain_db"] = 0.0
        out.append(band)
    return out


def export_eq_catalog() -> dict[str, Any]:
    """Full EQ catalog for the web UI (presets + band definitions)."""
    return {
        "presets": list_eq_presets(),
        "bands": {k: get_preset_bands(k) for k in EQ_PRESET_LABELS if k != "custom"},
    }


def normalize_bands(bands: list[dict]) -> list[dict[str, Any]]:
    """Validate/sanitize band list from the UI."""
    allowed = {"highpass", "lowpass", "peak", "low_shelf", "high_shelf"}
    clean: list[dict[str, Any]] = []
    for i, raw in enumerate(bands or []):
        ftype = (raw.get("type") or "peak").lower()
        if ftype not in allowed:
            continue
        spec: dict[str, Any] = {
            "type": ftype,
            "freq": max(20.0, min(float(raw.get("freq", 1000)), 20000.0)),
            "q": max(0.1, min(float(raw.get("q", 0.71)), 18.0)),
        }
        if ftype in ("peak", "low_shelf", "high_shelf"):
            spec["gain_db"] = max(-24.0, min(float(raw.get("gain_db", 0.0)), 24.0))
        clean.append(spec)
    return clean


@dataclass
class _BiquadCoeffs:
    b0: float
    b1: float
    b2: float
    a1: float
    a2: float


def _make_coeffs(spec: dict[str, Any], sr: float) -> _BiquadCoeffs:
    ftype = spec["type"]
    freq = max(20.0, min(float(spec["freq"]), sr * 0.49))
    q = max(0.1, float(spec.get("q", 0.707)))
    gain_db = float(spec.get("gain_db", 0.0))
    w0 = 2.0 * math.pi * freq / sr
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    alpha = sin_w0 / (2.0 * q)

    if ftype == "lowpass":
        b0 = (1.0 - cos_w0) / 2.0
        b1 = 1.0 - cos_w0
        b2 = (1.0 - cos_w0) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha
    elif ftype == "highpass":
        b0 = (1.0 + cos_w0) / 2.0
        b1 = -(1.0 + cos_w0)
        b2 = (1.0 + cos_w0) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha
    elif ftype == "peak":
        a = 10.0 ** (gain_db / 40.0)
        b0 = 1.0 + alpha * a
        b1 = -2.0 * cos_w0
        b2 = 1.0 - alpha * a
        a0 = 1.0 + alpha / a
        a1 = -2.0 * cos_w0
        a2 = 1.0 - alpha / a
    elif ftype == "low_shelf":
        a = 10.0 ** (gain_db / 40.0)
        sqrt_a = math.sqrt(a)
        b0 = a * ((a + 1.0) - (a - 1.0) * cos_w0 + 2.0 * sqrt_a * alpha)
        b1 = 2.0 * a * ((a - 1.0) - (a + 1.0) * cos_w0)
        b2 = a * ((a + 1.0) - (a - 1.0) * cos_w0 - 2.0 * sqrt_a * alpha)
        a0 = (a + 1.0) + (a - 1.0) * cos_w0 + 2.0 * sqrt_a * alpha
        a1 = -2.0 * ((a - 1.0) + (a + 1.0) * cos_w0)
        a2 = (a + 1.0) + (a - 1.0) * cos_w0 - 2.0 * sqrt_a * alpha
    elif ftype == "high_shelf":
        a = 10.0 ** (gain_db / 40.0)
        sqrt_a = math.sqrt(a)
        b0 = a * ((a + 1.0) + (a - 1.0) * cos_w0 + 2.0 * sqrt_a * alpha)
        b1 = -2.0 * a * ((a - 1.0) + (a + 1.0) * cos_w0)
        b2 = a * ((a + 1.0) + (a - 1.0) * cos_w0 - 2.0 * sqrt_a * alpha)
        a0 = (a + 1.0) - (a - 1.0) * cos_w0 + 2.0 * sqrt_a * alpha
        a1 = 2.0 * ((a - 1.0) - (a + 1.0) * cos_w0)
        a2 = (a + 1.0) - (a - 1.0) * cos_w0 - 2.0 * sqrt_a * alpha
    else:
        raise ValueError(f"unknown filter type: {ftype}")

    inv = 1.0 / a0
    return _BiquadCoeffs(b0 * inv, b1 * inv, b2 * inv, a1 * inv, a2 * inv)


class _Biquad:
    __slots__ = ("b0", "b1", "b2", "a1", "a2", "z1", "z2")

    def __init__(self, coeffs: _BiquadCoeffs, channels: int):
        self.b0, self.b1, self.b2, self.a1, self.a2 = (
            coeffs.b0, coeffs.b1, coeffs.b2, coeffs.a1, coeffs.a2,
        )
        self.z1 = np.zeros(channels, dtype=np.float64)
        self.z2 = np.zeros(channels, dtype=np.float64)

    def process(self, block: np.ndarray) -> np.ndarray:
        """block: (frames, channels) float32 -> float32"""
        out = np.empty_like(block, dtype=np.float32)
        ch = block.shape[1]
        for c in range(ch):
            x = block[:, c].astype(np.float64)
            y = np.empty_like(x)
            z1 = self.z1[c]
            z2 = self.z2[c]
            b0, b1, b2, a1, a2 = self.b0, self.b1, self.b2, self.a1, self.a2
            for i in range(x.shape[0]):
                yi = b0 * x[i] + z1
                z1 = b1 * x[i] - a1 * yi + z2
                z2 = b2 * x[i] - a2 * yi
                y[i] = yi
            self.z1[c] = z1
            self.z2[c] = z2
            out[:, c] = y.astype(np.float32)
        return out

    def reset(self) -> None:
        self.z1[:] = 0.0
        self.z2[:] = 0.0


class LiveEQ:
    """Thread-safe live EQ applied to playback blocks."""

    def __init__(self, sample_rate: int = 24000, channels: int = 1,
                 preset: str = "off", enabled: bool = True):
        self.channels = channels
        self._lock = threading.Lock()
        self._sample_rate = sample_rate
        self._preset = "off"
        self._enabled = True
        self._filters: list[_Biquad] = []
        self._custom_specs: list[dict[str, Any]] | None = None
        self.set_preset(preset)
        self.enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        with self._lock:
            self._enabled = bool(value)

    @property
    def preset(self) -> str:
        with self._lock:
            return self._preset

    def set_sample_rate(self, sample_rate: int) -> None:
        with self._lock:
            if sample_rate != self._sample_rate:
                self._sample_rate = sample_rate
                self._rebuild_locked()

    def set_preset(self, preset: str) -> None:
        preset = (preset or "off").lower()
        if preset not in EQ_PRESET_LABELS:
            preset = "off"
        with self._lock:
            self._preset = preset
            if preset != "custom":
                self._custom_specs = None
            self._rebuild_locked()

    def set_custom_bands(self, bands: list[dict]) -> None:
        """Apply a user-edited band list (switches preset to 'custom')."""
        specs = normalize_bands(bands)
        with self._lock:
            self._preset = "custom"
            self._custom_specs = specs
            EQ_PRESETS["custom"] = specs
            self._rebuild_locked()

    def get_bands(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._bands_locked()

    def _bands_locked(self) -> list[dict[str, Any]]:
        """Build the annotated band list. Caller must hold self._lock."""
        if self._preset == "custom" and self._custom_specs is not None:
            specs = list(self._custom_specs)
        else:
            specs = list(EQ_PRESETS.get(self._preset, []))
        out: list[dict[str, Any]] = []
        for i, spec in enumerate(specs):
            band = dict(spec)
            band["id"] = i
            band["color"] = EQ_BAND_COLORS[i % len(EQ_BAND_COLORS)]
            if band["type"] in ("highpass", "lowpass") and "gain_db" not in band:
                band["gain_db"] = 0.0
            out.append(band)
        return out

    def _rebuild_locked(self) -> None:
        if self._preset == "custom" and self._custom_specs is not None:
            specs = self._custom_specs
        else:
            specs = EQ_PRESETS.get(self._preset, [])
        self._filters = [_Biquad(_make_coeffs(s, self._sample_rate), self.channels)
                         for s in specs]

    def process(self, block: np.ndarray) -> np.ndarray:
        if block.size == 0:
            return block
        with self._lock:
            if not self._enabled or not self._filters:
                return block
            out = block
            for filt in self._filters:
                out = filt.process(out)
            np.clip(out, -1.0, 1.0, out=out)
            return out

    def reset(self) -> None:
        with self._lock:
            for filt in self._filters:
                filt.reset()

    def status(self) -> dict:
        with self._lock:
            return {
                "enabled": self._enabled,
                "preset": self._preset,
                "label": EQ_PRESET_LABELS.get(self._preset, self._preset),
                "bands": self._bands_locked(),
            }
