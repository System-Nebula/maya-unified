"""Tests for heuristic planner."""

from maya_contracts import ResearchSourceKind, SubTaskType
from maya_research.agent.nodes.planner import _heuristic_plan


def test_heuristic_plan_includes_web_and_reddit():
    plan = _heuristic_plan(
        "Krea 2 technical analysis",
        {
            ResearchSourceKind.WEB.value,
            ResearchSourceKind.REDDIT.value,
        },
        seed_urls=["https://www.krea.ai/blog/krea-2"],
    )
    types = {s.type for s in plan.subtasks}
    assert SubTaskType.WEB_SEARCH in types
    assert SubTaskType.REDDIT in types
    assert SubTaskType.PAGE_FETCH in types
    assert len(plan.subtasks) >= 4
