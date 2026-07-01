"""Tests for grouped inbox summary."""

from datetime import datetime, timezone

import pytest

from maya_gateway.services.discover_rank import get_inbox_summary


class _FakeRow:
    def __init__(self, slug: str, display: str, title: str, color: str):
        self.artist_slug = slug
        self.artist_display = display
        self.title = title
        self.brand_color = color
        self.received_at = datetime.now(timezone.utc)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    async def execute(self, _stmt):
        return _FakeResult(
            [
                _FakeRow("olivia-rodrigo", "Olivia Rodrigo", "New music", "#ec4899"),
            ]
        )


@pytest.mark.anyio
async def test_inbox_summary_groups_by_artist():
    summary = await get_inbox_summary(_FakeSession(), "local", window="7d")
    assert summary.total == 1
    assert len(summary.artists) == 1
    assert summary.artists[0].artist_display == "Olivia Rodrigo"
    assert summary.artists[0].count == 1
