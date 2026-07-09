"""Tracklist URL filter tests."""

from __future__ import annotations

from maya_feeds.tracklist.filter import classify_tracklist_url, is_tracklist_url
from maya_feeds.tracklist.protocol import TracklistPlatform


def test_youtube_watch_urls_match():
    assert is_tracklist_url("https://www.youtube.com/watch?v=gfF8jzBVWvM")
    assert classify_tracklist_url("https://youtu.be/gfF8jzBVWvM") == TracklistPlatform.YOUTUBE


def test_youtube_bare_watch_rejected():
    assert not is_tracklist_url("https://www.youtube.com/watch")
    assert classify_tracklist_url("https://www.youtube.com/watch") is None


def test_1001tracklists_urls_match():
    url = "https://www.1001tracklists.com/tracklist/2gu8q2xk/fred-again.html"
    assert is_tracklist_url(url)
    assert classify_tracklist_url(url) == TracklistPlatform.TRACKLISTS_1001


def test_apple_music_album_urls_match():
    url = "https://music.apple.com/us/album/alexandra-palace-london-feb-27-2026-dj-mix/1890298647"
    assert is_tracklist_url(url)
    assert classify_tracklist_url(url) == TracklistPlatform.APPLE_MUSIC


def test_non_tracklist_urls_rejected():
    assert not is_tracklist_url("https://example.com/playlist")
    assert not is_tracklist_url("https://open.spotify.com/album/abc")
    assert classify_tracklist_url("") is None
