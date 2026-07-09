"""Tests for autonomous goal-driven game play."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.game.agent_loop import _infer_action_from_raw, _parse_turn_json  # noqa: E402
from services.game.neuro_server import GameHub  # noqa: E402
from services.game.neuro_session import NeuroSession  # noqa: E402


def test_parse_turn_json_with_say_and_goal():
    allowed = {"press_a", "wait"}
    raw = """{
        "action": "press_a",
        "data": {},
        "say": "Okay, pressing A to talk to this nerd. This is a very long sentence to satisfy the filter.",
        "goal_reached": false,
        "goal_progress": "Still in Pallet Town"
    }"""
    parsed = _parse_turn_json(raw, allowed)
    assert parsed["action"] == "press_a"
    assert "nerd" in parsed["say"]
    assert parsed["goal_reached"] is False
    assert "Pallet" in parsed["goal_progress"]


def test_parse_turn_json_goal_reached():
    allowed = {"wait"}
    raw = '{"action": "wait", "say": "We made it!", "goal_reached": true, "goal_progress": "done"}'
    parsed = _parse_turn_json(raw, allowed)
    assert parsed["goal_reached"] is True


def test_parse_turn_json_recovers_when_action_is_say():
    allowed = {"press_a", "press_b", "wait", "press_down"}
    raw = """{
        "action": "say",
        "say": "Professor Oak is yapping again. Fine, I'll mash A. This is another very long sentence.",
        "goal_reached": false,
        "goal_progress": "intro"
    }"""
    parsed = _parse_turn_json(raw, allowed)
    assert parsed["action"] == "press_a"
    assert "Oak" in parsed["say"]


def test_parse_turn_json_strips_voice_action_and_recovers_press():
    allowed = {"press_down", "press_a", "wait"}
    raw = """{
        "action": "VOICE: bored, dismissive, sighing",
        "say": "",
        "goal_reached": false,
        "goal_progress": ""
    }"""
    # Without embedded action, infer from raw or fail — add press_down in raw
    raw2 = raw.replace('"goal_progress": ""', '"goal_progress": "walk press_down"')
    parsed = _parse_turn_json(raw2, allowed)
    assert parsed["action"] == "press_down"
    assert "VOICE" not in parsed["say"]


def test_infer_action_from_raw():
    allowed = {"press_left", "press_a", "wait"}
    raw = 'thought... {"action": "press_left", "say": ""}'
    assert _infer_action_from_raw(raw, allowed) == "press_left"


def test_parse_turn_json_normalizes_press_a_alias():
    allowed = {"press_a", "wait"}
    raw = '{"action": "press A", "say": "Talking.", "goal_reached": false, "goal_progress": ""}'
    parsed = _parse_turn_json(raw, allowed)
    assert parsed["action"] == "press_a"


def test_neuro_session_autonomous_goal():
    session = NeuroSession(operator_id="op-1", session_id="s1")
    session.set_autonomous_goal("reach Viridian City")
    assert session.goal == "reach Viridian City"
    assert session.autonomous is True
    assert session.goal_reached is False

    session.record_turn(
        action="press_up",
        say="Walking north, obviously.",
        goal_progress="Left Pallet Town",
        goal_reached=False,
    )
    assert session.turn_count == 1
    assert session.goal_progress == "Left Pallet Town"

    session.record_turn(
        action="wait",
        say="Viridian City! Took you long enough.",
        goal_progress="Arrived",
        goal_reached=True,
    )
    assert session.goal_reached is True
    assert session.autonomous is False


def test_game_hub_start_autonomous_pending():
    hub = GameHub()
    result = hub.start_autonomous("op-42", "beat Brock")
    assert result["ok"]
    assert result["goal"] == "beat Brock"
    st = hub.status("op-42")
    assert st["autonomous"] is True
    assert st["goal"] == "beat Brock"
    hub.on_goal_reached("op-42")
    st2 = hub.status("op-42")
    assert st2.get("goal") != "beat Brock" or not st2.get("autonomous")
