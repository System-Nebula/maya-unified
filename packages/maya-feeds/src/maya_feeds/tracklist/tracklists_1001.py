"""1001tracklists document parser."""

from __future__ import annotations

from typing import Any

from maya_feeds.tracklist.filter import classify_tracklist_url
from maya_feeds.tracklist.protocol import TracklistPlatform
from maya_feeds.tracklists_1001 import parse_1001tracklists_html


class Tracklists1001Parser:
    platform = TracklistPlatform.TRACKLISTS_1001

    def matches_url(self, url: str) -> bool:
        return classify_tracklist_url(url) == TracklistPlatform.TRACKLISTS_1001

    def parse(self, url: str, document: Any):
        if not isinstance(document, str):
            return None
        return parse_1001tracklists_html(url, document)
