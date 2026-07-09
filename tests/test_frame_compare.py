"""Tests for pre-action frame stability checks."""

from __future__ import annotations

import base64
import sys
from io import BytesIO
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.game.frame_compare import (  # noqa: E402
    frame_similarity,
    frame_stable_enough,
    hash_png_base64,
)

_RED_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8Dw"
    "HwAFBQIAX8j0SeAAAAAASUVORK5CYII="
)
_DATA_RED = f"data:image/png;base64,{_RED_B64}"


def _pattern_png(kind: str) -> str:
    from PIL import Image

    if kind == "overworld":
        img = Image.new("RGB", (240, 160), (88, 144, 88))
        px = img.load()
        for x in range(40, 200):
            for y in range(60, 140):
                px[x, y] = (32, 96, 32)
    elif kind == "nes":
        img = Image.new("RGB", (240, 160), (0, 0, 0))
        px = img.load()
        for x in range(20, 220):
            for y in range(40, 120):
                px[x, y] = (200, 200, 200) if (x // 8) % 2 == (y // 8) % 2 else (80, 80, 200)
    else:
        raise ValueError(kind)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_hash_png_base64_stable():
    h1 = hash_png_base64(_DATA_RED)
    h2 = hash_png_base64(_RED_B64)
    assert h1 == h2
    assert len(h1) == 16


def test_identical_frames_high_similarity():
    ow = _pattern_png("overworld")
    assert frame_similarity(ow, ow) == 1.0


def test_scene_change_below_stability_threshold():
    ow = _pattern_png("overworld")
    nes = _pattern_png("nes")
    sim = frame_similarity(ow, nes)
    ok, _ = frame_stable_enough(ow, nes, min_similarity=0.85)
    assert sim < 0.85
    assert ok is False


def test_frame_stable_enough_same_scene():
    ow = _pattern_png("overworld")
    ok, sim = frame_stable_enough(ow, ow, min_similarity=0.85)
    assert ok is True
    assert sim == 1.0


if __name__ == "__main__":
    test_hash_png_base64_stable()
    test_identical_frames_high_similarity()
    test_scene_change_below_stability_threshold()
    test_frame_stable_enough_same_scene()
    print("ok")
