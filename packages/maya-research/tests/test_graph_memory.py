"""Tests for delta-research mode selection."""

from datetime import datetime, timezone

import pytest

from maya_contracts import PriorResearchRef
from maya_research.storage.graph_memory import should_use_delta_mode


@pytest.mark.asyncio
async def test_delta_mode_for_high_similarity_shallow():
    prior = [
        PriorResearchRef(
            id="abc",
            title="Krea 2",
            brief="Krea 2 analysis",
            summary="Prior summary",
            researched_at=datetime.now(timezone.utc),
            similarity_score=0.9,
        )
    ]
    delta, since = await should_use_delta_mode(prior, "shallow")
    assert delta is True
    assert since is not None


@pytest.mark.asyncio
async def test_no_delta_for_deep():
    prior = [
        PriorResearchRef(
            id="abc",
            title="Krea 2",
            brief="Krea 2 analysis",
            summary="Prior summary",
            researched_at=datetime.now(timezone.utc),
            similarity_score=0.9,
        )
    ]
    delta, _ = await should_use_delta_mode(prior, "deep")
    assert delta is False
