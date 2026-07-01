"""Parser tests for the operator-facing channel resolver.

These guard the +Add person modal preview: paste a URL/handle/id and the
panel should render a sensible ChannelRef without contacting any platform.
"""

from __future__ import annotations

import pytest
from maya_contracts import Platform, ResolveChannelRequest

from maya_gateway.services.follow_resolve import resolve


@pytest.mark.parametrize(
    "raw, expected_id, expected_handle",
    [
        (
            "https://www.youtube.com/@MissKatie",
            "@MissKatie",
            "@MissKatie",
        ),
        ("@MissKatie", None, None),  # bare handle requires hint_platform
        (
            "https://www.youtube.com/channel/UCFldqmSKhOZQZdfUuPMJjpw",
            "UCFldqmSKhOZQZdfUuPMJjpw",
            "UCFldqmSKhOZQZdfUuPMJjpw",
        ),
        (
            "UCFldqmSKhOZQZdfUuPMJjpw",
            "UCFldqmSKhOZQZdfUuPMJjpw",
            "UCFldqmSKhOZQZdfUuPMJjpw",
        ),
        (
            "yt:UCFldqmSKhOZQZdfUuPMJjpw",
            "UCFldqmSKhOZQZdfUuPMJjpw",
            "UCFldqmSKhOZQZdfUuPMJjpw",
        ),
        (
            "yt:@MissKatie",
            "@MissKatie",
            "@MissKatie",
        ),
    ],
)
def test_youtube_inputs(raw: str, expected_id: str | None, expected_handle: str | None) -> None:
    """Each common shape of YouTube input either resolves to YouTube or is
    deliberately ambiguous (bare ``@handle`` is shared with IG/TikTok)."""

    if expected_id is None:
        with pytest.raises(ValueError):
            resolve(ResolveChannelRequest(input=raw))
        return

    resp = resolve(ResolveChannelRequest(input=raw))
    assert resp.channel.platform is Platform.YOUTUBE
    assert resp.channel.platform_id == expected_id
    assert resp.channel.handle == expected_handle
    assert resp.cross_platform_candidates == []


def test_youtube_feed_url_when_channel_id_known() -> None:
    """A canonical UC… channel id yields the Atom feed URL immediately so
    the FeedPoller can start polling without an enrichment round-trip."""

    resp = resolve(
        ResolveChannelRequest(input="UCFldqmSKhOZQZdfUuPMJjpw")
    )
    assert resp.channel.feed_url == (
        "https://www.youtube.com/feeds/videos.xml?"
        "channel_id=UCFldqmSKhOZQZdfUuPMJjpw"
    )


def test_youtube_handle_only_has_no_feed_url() -> None:
    """Without the UC… channel id we can't build the Atom feed URL — the
    enrichment worker fills this in on first contact."""

    resp = resolve(
        ResolveChannelRequest(input="yt:@MissKatie")
    )
    assert resp.channel.feed_url is None


@pytest.mark.parametrize(
    "raw, expected_handle",
    [
        ("https://instagram.com/heymisskatie", "@heymisskatie"),
        ("https://www.instagram.com/heymisskatie/", "@heymisskatie"),
        ("ig:heymisskatie", "@heymisskatie"),
        ("ig:@heymisskatie", "@heymisskatie"),
    ],
)
def test_instagram_inputs(raw: str, expected_handle: str) -> None:
    resp = resolve(ResolveChannelRequest(input=raw))
    assert resp.channel.platform is Platform.INSTAGRAM
    assert resp.channel.handle == expected_handle


@pytest.mark.parametrize(
    "raw, expected_handle",
    [
        ("https://tiktok.com/@heymisskatiee", "@heymisskatiee"),
        ("https://www.tiktok.com/@heymisskatiee", "@heymisskatiee"),
        ("tt:heymisskatiee", "@heymisskatiee"),
    ],
)
def test_tiktok_inputs(raw: str, expected_handle: str) -> None:
    resp = resolve(ResolveChannelRequest(input=raw))
    assert resp.channel.platform is Platform.TIKTOK
    assert resp.channel.handle == expected_handle


def test_hint_platform_breaks_handle_ambiguity() -> None:
    """``@misskatie`` could be any platform; the hint disambiguates."""

    yt = resolve(
        ResolveChannelRequest(input="@MissKatie", hint_platform=Platform.YOUTUBE)
    )
    assert yt.channel.platform is Platform.YOUTUBE
    assert yt.channel.handle == "@MissKatie"

    ig = resolve(
        ResolveChannelRequest(input="@heymisskatie", hint_platform=Platform.INSTAGRAM)
    )
    assert ig.channel.platform is Platform.INSTAGRAM

    tt = resolve(
        ResolveChannelRequest(
            input="@heymisskatiee", hint_platform=Platform.TIKTOK
        )
    )
    assert tt.channel.platform is Platform.TIKTOK


def test_empty_input_raises() -> None:
    with pytest.raises(ValueError):
        resolve(ResolveChannelRequest(input="   "))


def test_garbage_input_raises_without_hint() -> None:
    with pytest.raises(ValueError):
        resolve(ResolveChannelRequest(input="random garbage 🌀"))
