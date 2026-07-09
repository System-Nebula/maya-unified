"""Tests for FireRed playbook helpers."""

from services.game.frlg_playbook import STORY_MILESTONES, milestone_context


def test_story_milestones_cover_elite_four():
    assert any("Elite Four" in step for step in STORY_MILESTONES)


def test_milestone_context_includes_goal():
    text = milestone_context(goal="Beat Elite Four", goal_progress="In Viridian Forest", turn=42)
    assert "Beat Elite Four" in text
    assert "Viridian Forest" in text
    assert "Turn:** 42" in text
    assert "Leave player bedroom" in text
