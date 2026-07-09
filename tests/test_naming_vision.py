"""Tests for vision-guided naming action parsing."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.game.naming_vision import (  # noqa: E402
    parse_entered_from_prose,
    pick_naming_action_sync,
)


def test_parse_entered_from_prose_backtick_pattern():
    raw = 'The letter M has been selected (indicated by `_M______`).'
    assert parse_entered_from_prose(raw) == "M"


def test_parse_entered_from_prose_rejects_target_echo():
    raw = 'TARGET name to spell: MAYA. The name box is empty.'
    assert parse_entered_from_prose(raw, target="MAYA") == ""


def test_pick_naming_action_rejects_untyped_full_name():
    allowed = {"press_up", "press_down", "press_left", "press_right", "press_a", "press_b"}
    fake = '{"entered": "MAYA", "cursor_on": "OK", "action": "press_a", "done": true}'
    with patch("services.game.agent_loop._vision_complete", return_value=fake):
        picked = pick_naming_action_sync(
            b"png",
            target="MAYA",
            operator_id="op",
            allowed=allowed,
            typed_letters=0,
        )
    assert picked["done_explicit"] is False


def test_pick_naming_action_parses_json():
    allowed = {"press_up", "press_down", "press_left", "press_right", "press_a", "press_b"}
    fake = '{"entered": "M", "cursor_on": "A", "action": "press_a", "done": false}'
    with patch("services.game.agent_loop._vision_complete", return_value=fake):
        picked = pick_naming_action_sync(
            b"png",
            target="MAYA",
            operator_id="op",
            allowed=allowed,
        )
    assert picked["entered"] == "M"
    assert picked["action"] == "press_a"
    assert picked["cursor_on"] == "A"


def test_pick_naming_action_prose_fallback_no_blind_backspace():
    allowed = {"press_b", "press_down", "press_up"}
    fake = "The name box is empty. I should press_down to reach M."
    with patch("services.game.agent_loop._vision_complete", return_value=fake):
        picked = pick_naming_action_sync(
            b"png",
            target="MAYA",
            operator_id="op",
            allowed=allowed,
        )
    assert picked["action"] != "press_b"


if __name__ == "__main__":
    test_parse_entered_from_prose_backtick_pattern()
    test_parse_entered_from_prose_rejects_target_echo()
    test_pick_naming_action_parses_json()
    test_pick_naming_action_prose_fallback_no_blind_backspace()
    test_pick_naming_action_rejects_untyped_full_name()
    print("ok")
