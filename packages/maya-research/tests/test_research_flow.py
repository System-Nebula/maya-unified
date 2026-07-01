"""Integration-style test for shallow research with mocked sources."""

from unittest.mock import AsyncMock, patch

import pytest

from maya_contracts import WebSearchResult
from maya_research.agent.graph import run_research_planning
from maya_research.agent.state import ResearchState


@pytest.mark.asyncio
async def test_planning_phase_produces_plan():
    state: ResearchState = {
        "run_id": "",
        "brief": "Test topic research",
        "depth": "shallow",
        "source_mask": ["web", "reddit"],
        "seed_urls": [],
        "operator_id": "local",
        "plan_approved": False,
        "errors": [],
        "progress": [],
    }
    with patch(
        "maya_research.agent.nodes.coordinator.find_prior_research",
        new=AsyncMock(return_value=[]),
    ):
        result = await run_research_planning(state)
    assert result.get("plan") is not None
    assert len(result["plan"].subtasks) >= 2
    assert result.get("plan_approved") is True
