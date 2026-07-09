"""Tests for game frame stash dedup."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.game import frames as game_frames  # noqa: E402

# 1x1 PNG
_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
_DATA_URL = f"data:image/png;base64,{_PNG_B64}"


@pytest.fixture(autouse=True)
def _clear_frames():
    game_frames.clear_frame("op-test", session_id="sess")
    yield
    game_frames.clear_frame("op-test", session_id="sess")


def test_put_frame_increments_seq():
    r1 = game_frames.put_frame("op-test", _DATA_URL, session_id="sess")
    r2 = game_frames.put_frame("op-test", _DATA_URL, session_id="sess")
    assert r1["ok"] and r2["ok"]
    assert r2["frame_seq"] > r1["frame_seq"]


def test_frame_changed_detects_same_hash():
    game_frames.put_frame("op-test", _DATA_URL, session_id="sess")
    frame = game_frames.get_frame("op-test", session_id="sess")
    assert frame is not None
    assert game_frames.frame_changed("op-test", session_id="sess", since_hash=frame.content_hash) is False
    assert game_frames.frame_changed("op-test", session_id="sess", since_hash="other") is True


def test_frame_ref_format():
    ref = game_frames.frame_ref("abc-123", "sess1")
    assert ref == "game:abc-123:sess1"
