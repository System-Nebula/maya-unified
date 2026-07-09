"""FPS-based game capture / analysis timing (profile + operator overrides)."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


@dataclass
class GameTiming:
    poll_fps: float
    analysis_fps_min: float
    analysis_fps_max: float
    tts_ms_per_char: int = 30
    tts_extra_cap_ms: int = 2500
    naming_turn_pause_ms: int = 120

    @property
    def poll_ms(self) -> int:
        return max(50, int(1000 / max(self.poll_fps, 0.1)))

    @property
    def min_analysis_gap_ms(self) -> int:
        """Shortest allowed gap between vision turns (fastest analysis rate)."""
        return max(400, int(1000 / max(self.analysis_fps_max, 0.01)))

    @property
    def max_analysis_gap_ms(self) -> int:
        """Longest base gap between vision turns (slowest analysis rate)."""
        return max(self.min_analysis_gap_ms, int(1000 / max(self.analysis_fps_min, 0.01)))

    def turn_pause_ms(self, last_say: str = "", *, naming_active: bool = False) -> int:
        """Pause after a turn. Silent turns use the minimum gap only."""
        if naming_active:
            return max(60, self.naming_turn_pause_ms)
        lo = self.min_analysis_gap_ms
        hi = self.max_analysis_gap_ms
        say = (last_say or "").strip()
        if not say:
            return lo
        base = random.randint(lo, hi)
        extra = min(len(say) * self.tts_ms_per_char, self.tts_extra_cap_ms)
        return base + extra

    def to_dict(self) -> dict[str, Any]:
        return {
            "poll_fps": self.poll_fps,
            "analysis_fps_min": self.analysis_fps_min,
            "analysis_fps_max": self.analysis_fps_max,
            "poll_ms": self.poll_ms,
            "min_analysis_gap_ms": self.min_analysis_gap_ms,
            "max_analysis_gap_ms": self.max_analysis_gap_ms,
            "tts_ms_per_char": self.tts_ms_per_char,
            "tts_extra_cap_ms": self.tts_extra_cap_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameTiming:
        return cls(
            poll_fps=float(data.get("poll_fps") or 4),
            analysis_fps_min=float(data.get("analysis_fps_min") or 0.4),
            analysis_fps_max=float(data.get("analysis_fps_max") or 1.0),
            tts_ms_per_char=int(data.get("tts_ms_per_char") or 22),
            tts_extra_cap_ms=int(data.get("tts_extra_cap_ms") or 1200),
            naming_turn_pause_ms=int(data.get("naming_turn_pause_ms") or 120),
        )


def _float_or_zero(val: Any) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def resolve_game_timing(profile: Any, operator_settings: dict[str, Any] | None = None) -> GameTiming:
    """Merge profile YAML defaults with per-operator `settings.game` overrides."""
    capture = dict(getattr(profile, "capture", None) or {})
    policy = dict(getattr(profile, "turn_policy", None) or {})
    root = operator_settings if isinstance(operator_settings, dict) else {}
    og = root.get("game") if isinstance(root.get("game"), dict) else {}

    poll_fps = _float_or_zero(og.get("poll_fps"))
    if not poll_fps:
        poll_fps = _float_or_zero(capture.get("poll_fps") or capture.get("max_fps") or 4)

    analysis_fps_min = _float_or_zero(og.get("analysis_fps_min") or policy.get("analysis_fps_min"))
    analysis_fps_max = _float_or_zero(og.get("analysis_fps_max") or policy.get("analysis_fps_max"))

    if not analysis_fps_min and policy.get("max_interval_ms"):
        analysis_fps_min = 1000 / max(int(policy["max_interval_ms"]), 1)
    if not analysis_fps_max and policy.get("min_interval_ms"):
        analysis_fps_max = 1000 / max(int(policy["min_interval_ms"]), 1)

    if not analysis_fps_min:
        analysis_fps_min = 0.4
    if not analysis_fps_max:
        analysis_fps_max = 1.0
    if analysis_fps_max < analysis_fps_min:
        analysis_fps_min, analysis_fps_max = analysis_fps_max, analysis_fps_min

    tts_ms = int(og.get("tts_ms_per_char") or policy.get("tts_ms_per_char") or 22)
    tts_cap = int(og.get("tts_extra_cap_ms") or policy.get("tts_extra_cap_ms") or 1200)
    naming_pause = int(og.get("naming_turn_pause_ms") or policy.get("naming_turn_pause_ms") or 120)

    return GameTiming(
        poll_fps=max(poll_fps, 0.1),
        analysis_fps_min=max(analysis_fps_min, 0.01),
        analysis_fps_max=max(analysis_fps_max, 0.01),
        tts_ms_per_char=tts_ms,
        tts_extra_cap_ms=tts_cap,
        naming_turn_pause_ms=naming_pause,
    )
