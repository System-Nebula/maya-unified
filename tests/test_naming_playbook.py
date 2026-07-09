"""Tests for FRLG name-grid playbook."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.game.naming_playbook import (  # noqa: E402
    normalize_entered_name,
    plan_name_entry,
    plan_name_fix,
    take_naming_chunk,
)


def test_normalize_entered_name_empty_markers():
    assert normalize_entered_name("EMPTY") == ""
    assert normalize_entered_name("none") == ""
    assert normalize_entered_name("MAYA") == "MAYA"


def test_plan_name_fix_does_not_backspace_empty_marker():
    steps = plan_name_fix("EMPTY", "MAYA")
    assert steps[0] != "press_b"
    assert "press_a" in steps


def test_plan_name_suffix_continues_from_m():
    steps = plan_name_fix("M", "MAYA")
    assert "press_b" not in steps
    assert steps[0] == "press_up"
    assert steps.count("press_a") == 4


def test_plan_name_fix_clears_wrong_prefix():
    steps = plan_name_fix("MG", "MAYA")
    assert steps[0] == "press_b"
    assert steps.count("press_b") == 2


def test_take_naming_chunk_stops_before_confirm():
    queue = ["press_right", "press_right", "press_a", "press_down"]
    chunk = take_naming_chunk(queue, max_arrow_run=5)
    assert chunk == ["press_right", "press_right"]
    assert queue == ["press_a", "press_down"]


def test_maya_script_ends_on_ok_confirm():
    steps = plan_name_entry("MAYA")
    assert steps[-1] == "press_a"
    assert steps.count("press_a") == 5
    assert steps[:3] == ["press_down", "press_down", "press_a"]


def test_maya_does_not_start_with_j_path():
    steps = plan_name_entry("MAYA")
    assert steps[0] != "press_right"
    assert "press_right" not in steps[:2]


if __name__ == "__main__":
    test_normalize_entered_name_empty_markers()
    test_plan_name_fix_does_not_backspace_empty_marker()
    test_plan_name_suffix_continues_from_m()
    test_plan_name_fix_clears_wrong_prefix()
    test_take_naming_chunk_stops_before_confirm()
    test_maya_script_ends_on_ok_confirm()
    test_maya_does_not_start_with_j_path()
    print("ok")
