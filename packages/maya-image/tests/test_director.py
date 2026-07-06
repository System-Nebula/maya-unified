"""Tests for Image Director state, compile, and stopping logic."""

from __future__ import annotations

import pytest

from maya_image.director.compile import state_to_prompt
from maya_image.director.critique import merge_critiques
from maya_image.director.intent import _heuristic_parse
from maya_image.director.state import CritiqueRecord, HatGoal, ImageGoal, ImageSessionState
from maya_image.director.stopping import record_iteration, should_stop


def test_state_to_prompt_from_goal():
    goal = ImageGoal(
        subject="dog",
        expression="stupid",
        hat=HatGoal(type="runescape_blue_party_hat", color="blue"),
        style="painterly",
        composition="portrait",
    )
    prompt = state_to_prompt(goal)
    assert "dog" in prompt
    assert "stupid" in prompt
    assert "runescape blue party hat" in prompt.lower() or "runescape" in prompt.lower()
    assert "painterly" in prompt


def test_apply_delta_merges_hat():
    state = ImageSessionState(goal=ImageGoal(subject="dog"))
    state.apply_delta({"hat": {"type": "party_hat", "color": "blue"}})
    assert state.goal.hat is not None
    assert state.goal.hat.type == "party_hat"
    assert state.goal.hat.color == "blue"


def test_heuristic_intent_hat_edit():
    state = ImageSessionState(current_image_url="http://x/img.png")
    result = _heuristic_parse("make the hat more RuneScape", state)
    assert result["suggested_next_tool"] == "image_edit_region"
    assert result["state_delta"].get("hat", {}).get("type") == "runescape_blue_party_hat"


def test_should_stop_on_score():
    state = ImageSessionState()
    stop, reason = should_stop(state, score=0.92)
    assert stop is True
    assert reason == "score_acceptable"


def test_should_stop_on_iteration_cap():
    state = ImageSessionState()
    state.iteration.count = 3
    state.iteration.max_count = 3
    stop, reason = should_stop(state, score=0.5)
    assert stop is True
    assert reason == "iteration_cap"


def test_record_iteration_stall():
    state = ImageSessionState()
    record_iteration(state, score=0.6, issues=["hat wrong"])
    record_iteration(state, score=0.62, issues=["hat wrong"])
    assert state.iteration.stall_count == 1


def test_merge_critiques_deduplicates_issues():
    a = CritiqueRecord(critic="art", goal_match=0.7, issues=["hat wrong"])
    b = CritiqueRecord(critic="prompt", goal_match=0.8, issues=["hat wrong", "background busy"])
    merged = merge_critiques([a, b])
    assert merged.goal_match == pytest.approx(0.75)
    assert len(merged.issues) == 2
    assert merged.fixable_with_edit is True
