"""Tests for Twitch dead-air monologue prompt selection."""

from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1] / "packages" / "voice-runtime"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from stream_monologue import (  # noqa: E402
    STREAM_MONOLOGUE_POST_HISTORY,
    pick_monologue_prompt,
)


def test_monologue_prompt_avoids_silence_meta():
    assert "NEVER mention silence" in STREAM_MONOLOGUE_POST_HISTORY
    assert "monologue" in STREAM_MONOLOGUE_POST_HISTORY.lower()
    assert "Neuro-sama" in STREAM_MONOLOGUE_POST_HISTORY
    assert "Maya-sama" in STREAM_MONOLOGUE_POST_HISTORY


def test_monologue_prompt_has_no_user_facing_meta():
    _id, prompt = pick_monologue_prompt([], recent_mode_ids=deque())
    assert "[System:" not in prompt
    assert "dead air on stream" not in prompt.lower()
    assert "stream dead-air" not in prompt.lower()


def test_monologue_prompt_includes_anti_repeat():
    _id, prompt = pick_monologue_prompt(
        ["I already ranted about cookies and world domination."],
        recent_mode_ids=deque(),
    )
    assert _id
    assert "DO NOT repeat" in prompt
    assert "cookies" in prompt


def test_monologue_rotates_modes():
    recent = deque(["hot_take"])
    ids = set()
    for _ in range(8):
        mode_id, _ = pick_monologue_prompt([], recent_mode_ids=recent)
        ids.add(mode_id)
        recent.append(mode_id)
    assert len(ids) >= 3


if __name__ == "__main__":
    test_monologue_prompt_avoids_silence_meta()
    test_monologue_prompt_has_no_user_facing_meta()
    test_monologue_prompt_includes_anti_repeat()
    test_monologue_rotates_modes()
    print("ok")
