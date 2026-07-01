"""Tests for operator history adapter extension point."""

import pytest

from maya_contracts import OperatorContextItem
from maya_research.adapters.operator_history import (
    NullOperatorHistoryReader,
    StaticOperatorHistoryReader,
)


@pytest.mark.asyncio
async def test_null_reader_returns_empty():
    reader = NullOperatorHistoryReader()
    ctx = await reader.for_research("krea 2")
    assert ctx.query == "krea 2"
    assert ctx.items == []


@pytest.mark.asyncio
async def test_static_reader_for_tests():
    reader = StaticOperatorHistoryReader(
        [
            OperatorContextItem(
                url="https://www.krea.ai/blog/krea-2",
                title="Krea 2 blog",
            )
        ]
    )
    ctx = await reader.for_research("krea")
    assert len(ctx.items) == 1
