"""Tests for RSS URL parsing in follow_resolve."""

import pytest
from maya_contracts import Platform, ResolveChannelRequest

from maya_gateway.services.follow_resolve import resolve


@pytest.mark.parametrize(
    "input_text",
    [
        "https://ukf.com/read/feed/",
        "https://ukf.com/read/feed",
        "rss:https://ukf.com/read/feed/",
    ],
)
def test_rss_feed_url_resolves(input_text: str) -> None:
    resp = resolve(ResolveChannelRequest(input=input_text))
    assert resp.channel.platform == Platform.RSS
    assert "ukf.com/read/feed" in resp.channel.feed_url or ""
    assert resp.channel.platform_id.startswith("http")


def test_rss_hint_platform() -> None:
    resp = resolve(
        ResolveChannelRequest(
            input="ukf.com/read/feed/",
            hint_platform=Platform.RSS,
        )
    )
    assert resp.channel.platform == Platform.RSS
