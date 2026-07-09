"""Tests for music URL handler platform detection."""

from __future__ import annotations

from services.music.url_handler import detect_platform, PLATFORM_1001TL, PLATFORM_APPLE, PLATFORM_YOUTUBE


def test_detect_platform_youtube():
    assert detect_platform("https://www.youtube.com/watch?v=u1NHX9FcHVw") == PLATFORM_YOUTUBE
    assert detect_platform("https://youtu.be/gfF8jzBVWvM") == PLATFORM_YOUTUBE


def test_detect_platform_1001tracklists():
    url = "https://www.1001tracklists.com/tracklist/2gu8q2xk/fred-again.html"
    assert detect_platform(url) == PLATFORM_1001TL


def test_detect_platform_apple_music():
    url = "https://music.apple.com/us/album/alexandra-palace-london-feb-27-2026-dj-mix/1890298647"
    assert detect_platform(url) == PLATFORM_APPLE


def test_detect_platform_unknown():
    assert detect_platform("https://example.com/mix") is None
