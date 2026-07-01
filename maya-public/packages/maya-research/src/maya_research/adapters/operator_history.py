"""Operator browser history adapter protocol and null implementation.

Downstream wiring: see docs/research-internal-handoff.md (public) and
~/Workspace/docs/research-public-handoff.md (internal).
"""

from __future__ import annotations

from typing import Protocol

from maya_contracts import OperatorContext, OperatorContextItem


class OperatorHistoryReader(Protocol):
    async def for_research(self, query: str, *, window_days: int = 30) -> OperatorContext: ...


class NullOperatorHistoryReader:
    """Default public-branch adapter — no operator history available."""

    async def for_research(self, query: str, *, window_days: int = 30) -> OperatorContext:
        return OperatorContext(query=query, items=[])


class StaticOperatorHistoryReader:
    """Test helper that returns fixed seed URLs."""

    def __init__(self, items: list[OperatorContextItem]) -> None:
        self._items = items

    async def for_research(self, query: str, *, window_days: int = 30) -> OperatorContext:
        return OperatorContext(query=query, items=self._items)
