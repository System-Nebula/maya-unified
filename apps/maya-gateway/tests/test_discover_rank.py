"""Tests for discover feed ranking (in-memory / no DB when unavailable)."""

import pytest

from maya_gateway.services.discover_query import parse_discover_query


@pytest.mark.parametrize(
    "query,window,slug",
    [
        ("this week", "7d", None),
        ("this month skrillex", "30d", "skrillex"),
        ("/new this week", "7d", None),
    ],
)
def test_nl_windows(query: str, window: str, slug: str | None):
    parsed = parse_discover_query(query)
    assert parsed.window == window
    if slug:
        assert parsed.artist_slug == slug
