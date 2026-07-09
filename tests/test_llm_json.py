"""Tests for LLM JSON repair parsing."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.game.llm_json import parse_llm_json_dict, repair_truncated_json  # noqa: E402


def test_repair_truncated_json_closes_object():
    broken = '{"entered": "M", "action": "press_a"'
    fixed = repair_truncated_json(broken)
    data = parse_llm_json_dict(fixed)
    assert data == {"entered": "M", "action": "press_a"}


def test_json_repair_fixes_unquoted_keys():
    raw = 'Sure! {entered: M, cursor_on: A, action: press_a, done: false}'
    data = parse_llm_json_dict(raw, fallback_keys=("entered", "action"))
    assert data is not None
    assert data.get("entered") == "M"
    assert data.get("action") == "press_a"


def test_parse_turn_like_broken_json():
    raw = (
        'The user wants MAYA.\n'
        '{"action": "press_up", "say": "", "goal_reached": false, '
        '"goal_progress": "Moving to A"'
    )
    data = parse_llm_json_dict(
        raw,
        fallback_keys=("action", "say", "goal_reached", "goal_progress"),
    )
    assert data is not None
    assert data.get("action") == "press_up"


if __name__ == "__main__":
    test_repair_truncated_json_closes_object()
    test_json_repair_fixes_unquoted_keys()
    test_parse_turn_like_broken_json()
    print("ok")
