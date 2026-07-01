"""Downstream Discord integration hooks for research progress.

Downstream wiring: see docs/research-internal-handoff.md (public) and
~/Workspace/docs/research-public-handoff.md (internal).
"""

from __future__ import annotations

from typing import Protocol


class ResearchProgressPublisher(Protocol):
    async def post_progress(
        self,
        thread_id: str,
        *,
        stage: str,
        message: str,
    ) -> None: ...


class NullResearchProgressPublisher:
    """Public-branch default — Discord thread updates are wired downstream."""

    async def post_progress(
        self,
        thread_id: str,
        *,
        stage: str,
        message: str,
    ) -> None:
        return None
