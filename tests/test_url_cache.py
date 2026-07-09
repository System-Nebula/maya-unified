"""Tests for music URL fetch cache and trajectory trace."""

from __future__ import annotations

from services.music.url_cache import FetchTrace, cache_clear, cache_get, cache_set, normalize_url


def setup_function() -> None:
    cache_clear()


def test_normalize_url_strips_youtube_playlist_params():
    url = "https://www.youtube.com/watch?v=gfF8jzBVWvM&list=RDgfF8jzBVWvM"
    assert normalize_url(url) == "https://www.youtube.com/watch?v=gfF8jzBVWvM"


def test_cache_round_trip():
    cache_set("html", "https://example.com/page", "<html></html>", ttl_s=60)
    assert cache_get("html", "https://example.com/page") == "<html></html>"


def test_fetch_trace_serializes():
    trace = FetchTrace(
        seed_url="https://example.com/seed",
        fetched_urls=["https://example.com/a", "https://example.com/b"],
        platforms=["yt", "1001tl"],
    )
    data = trace.to_dict()
    assert data["seed_url"] == "https://example.com/seed"
    assert len(data["fetched_urls"]) == 2
