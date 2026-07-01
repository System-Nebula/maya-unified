"""Tests for discover query parsing."""

from maya_gateway.services.discover_query import parse_discover_query


def test_parse_this_week():
    parsed = parse_discover_query("what's new this week")
    assert parsed.window == "7d"
    assert parsed.artist_slug is None


def test_parse_this_month_skrillex():
    parsed = parse_discover_query("what's new this month for skrillex")
    assert parsed.window == "30d"
    assert parsed.artist_slug == "skrillex"


def test_parse_artist_only():
    parsed = parse_discover_query("skrillex")
    assert parsed.artist_slug == "skrillex"
