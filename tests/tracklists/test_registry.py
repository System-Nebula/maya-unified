"""Tracklist parser registry tests."""

from __future__ import annotations

import pytest

from maya_feeds.tracklist.protocol import TracklistPlatform
from maya_feeds.tracklist.registry import get_tracklist_parser, list_tracklist_platforms


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        ("https://www.youtube.com/watch?v=gfF8jzBVWvM", TracklistPlatform.YOUTUBE),
        (
            "https://www.1001tracklists.com/tracklist/2gu8q2xk/fred-again.html",
            TracklistPlatform.TRACKLISTS_1001,
        ),
        (
            "https://music.apple.com/us/album/alexandra-palace-london-feb-27-2026-dj-mix/1890298647",
            TracklistPlatform.APPLE_MUSIC,
        ),
    ],
)
def test_get_tracklist_parser_for_known_urls(url: str, platform: TracklistPlatform):
    parser = get_tracklist_parser(url)
    assert parser.platform == platform
    assert parser.matches_url(url)


def test_list_tracklist_platforms():
    platforms = list_tracklist_platforms()
    assert TracklistPlatform.YOUTUBE in platforms
    assert TracklistPlatform.TRACKLISTS_1001 in platforms
    assert TracklistPlatform.APPLE_MUSIC in platforms


def test_get_tracklist_parser_unknown_url_returns_none():
    assert get_tracklist_parser("https://example.com/not-a-set") is None
