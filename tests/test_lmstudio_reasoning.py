"""Tests for LM Studio Gemma-4 on/off reasoning mapping."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.game.lmstudio_reasoning import (  # noqa: E402
    normalize_lmstudio_reasoning_effort,
    think_prefix_for_model,
)


def test_low_maps_to_on():
    assert normalize_lmstudio_reasoning_effort("low", enabled=True) == "on"


def test_on_stays_on():
    assert normalize_lmstudio_reasoning_effort("on", enabled=True) == "on"


def test_disabled_is_off():
    assert normalize_lmstudio_reasoning_effort("low", enabled=False) == "off"
    assert normalize_lmstudio_reasoning_effort("on", enabled=False) == "off"


def test_none_maps_to_off_when_enabled():
    assert normalize_lmstudio_reasoning_effort("none", enabled=True) == "off"


def test_gemma4_think_prefix():
    assert think_prefix_for_model("google/gemma-4-26b-a4b") == "<|think|>"


def test_other_model_no_prefix():
    assert think_prefix_for_model("qwen3-vl") == ""


if __name__ == "__main__":
    test_low_maps_to_on()
    test_on_stays_on()
    test_disabled_is_off()
    test_none_maps_to_off_when_enabled()
    test_gemma4_think_prefix()
    test_other_model_no_prefix()
    print("ok")
