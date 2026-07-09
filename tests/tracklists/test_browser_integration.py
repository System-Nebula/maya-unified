"""Browser capture → tracklist pipeline integration (mocked S3)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from services.browser.tracklist_processor import process_tracklist_capture
from tests.helpers.music_set_fixtures import (
    FRED_AGAIN_1001TL_URL,
    seed_fred_again_fetch_cache,
)
from tests.tracklists.conftest import assert_set_contract


@pytest.mark.asyncio
async def test_process_tracklist_capture_indexes_and_links(monkeypatch):
    seed_fred_again_fetch_cache()
    html = b"<html>1001 fixture</html>"

    conn = AsyncMock()
    assets = [{"kind": "html", "key": "captures/test/page.html"}]

    async def _fake_fetch(_client, key):
        assert key == "captures/test/page.html"
        from tests.helpers.music_set_fixtures import TL_FIXTURES

        return (TL_FIXTURES / "fred_again_1001tl.html").read_bytes()

    monkeypatch.setattr(
        "services.browser.tracklist_processor.fetch_capture_asset",
        _fake_fetch,
    )
    monkeypatch.setattr(
        "services.browser.tracklist_processor.project_browser_capture",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "services.browser.tracklist_processor.link_capture_to_set",
        AsyncMock(),
    )

    async with httpx.AsyncClient() as client:
        result = await process_tracklist_capture(
            conn,
            capture_id="cap-123",
            url=FRED_AGAIN_1001TL_URL,
            title="Fred again 1001TL",
            assets=assets,
            http_client=client,
        )

    assert result is not None
    assert result["set_key"].startswith("yt:")
    assert result["entry_count"] == 3

    from services.music.url_handler import index_music_url

    resolved = await index_music_url(FRED_AGAIN_1001TL_URL, correlate=False, ingest=False)
    assert resolved is not None
    assert_set_contract(resolved)


@pytest.mark.asyncio
async def test_process_tracklist_capture_skips_non_tracklist_url():
    conn = AsyncMock()
    async with httpx.AsyncClient() as client:
        result = await process_tracklist_capture(
            conn,
            capture_id="cap-456",
            url="https://example.com/page",
            title="Not a set",
            assets=[],
            http_client=client,
        )
    assert result is None
