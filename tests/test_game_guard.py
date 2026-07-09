"""Tests for stuck-interact guard logic."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.game.agent_loop import (  # noqa: E402
    _guard_action,
    _pick_walkaway,
    _should_force_walkaway,
)
from services.game.neuro_session import NeuroSession  # noqa: E402


def _session_with_actions(actions: list[str]) -> NeuroSession:
    s = NeuroSession(operator_id="op", session_id="s")
    for act in actions:
        s.record_turn(action=act, say="", goal_progress="", goal_reached=False)
    return s


def test_guard_escapes_double_a_with_down():
    s = _session_with_actions(["press_a", "press_a"])
    allowed = {"press_a", "press_down", "press_left", "press_right", "press_up"}
    action, reason = _guard_action("press_a", s, allowed)
    assert action == "press_down"
    assert reason in ("a_streak_escape", "stuck_interact_loop")


def test_guard_unchanged_scene_plus_a_forces_walk():
    s = _session_with_actions(["press_a", "wait", "press_a"])
    s.unchanged_force_streak = 2
    allowed = {"press_a", "press_down", "press_left"}
    action, reason = _guard_action("press_a", s, allowed)
    assert action == "press_down"
    assert reason == "stuck_interact_loop"


def test_guard_skipped_during_naming():
    s = _session_with_actions(["press_a", "press_a"])
    s.unchanged_force_streak = 3
    s.naming_target = "MAYA"
    assert _should_force_walkaway(s, naming_active=True) is False


def test_pick_walkaway_avoids_repeating_same_arrow():
    s = _session_with_actions(["press_down", "press_down"])
    allowed = {"press_down", "press_left", "press_right"}
    assert _pick_walkaway(s, allowed) in ("press_left", "press_right")


def test_guard_blocks_consecutive_wait():
    s = _session_with_actions(["wait", "wait"])
    allowed = {"wait", "press_down", "advance_dialog"}
    action, reason = _guard_action("wait", s, allowed)
    assert action == "press_down"
    assert reason == "anti_wait_spam"


def test_guard_upgrades_press_a_to_advance_dialog():
    s = _session_with_actions(["press_a"])
    s.unchanged_force_streak = 1
    allowed = {"press_a", "advance_dialog", "press_down"}
    action, reason = _guard_action("press_a", s, allowed)
    assert action == "advance_dialog"
    assert reason == "dialog_burst"


def test_guard_skips_all_rules_during_naming():
    s = _session_with_actions(["press_a", "press_a", "press_a", "wait"])
    s.unchanged_force_streak = 5
    s.naming_target = "MAYA"
    allowed = {"press_a", "press_down", "press_left", "press_right", "advance_dialog"}
    action, reason = _guard_action("press_a", s, allowed)
    assert action == "press_a"
    assert reason is None


    s = _session_with_actions(["press_down", "press_down", "press_down"])
    s.naming_target = "MAYA"
    allowed = {"press_up", "press_down", "press_left", "press_right", "press_a"}
    action, reason = _guard_action("press_down", s, allowed)
    assert action == "press_down"
    assert reason is None


def test_guard_skips_anti_a_spam_during_naming():
    s = _session_with_actions(["press_a", "press_a"])
    s.naming_target = "MAYA"
    allowed = {"press_a", "press_down", "press_left", "press_right"}
    action, reason = _guard_action("press_a", s, allowed)
    assert action == "press_a"
    assert reason is None


if __name__ == "__main__":
    test_guard_escapes_double_a_with_down()
    test_guard_unchanged_scene_plus_a_forces_walk()
    test_guard_skipped_during_naming()
    test_pick_walkaway_avoids_repeating_same_arrow()
    test_guard_blocks_consecutive_wait()
    test_guard_upgrades_press_a_to_advance_dialog()
    test_guard_skips_all_rules_during_naming()
    test_guard_skips_anti_a_spam_during_naming()
    print("ok")
