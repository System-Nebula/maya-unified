"""slskd music-query smoke: search, FLAC filter, Never Gonna Give You Up 7\" download.

Unmarked tests use a fake slskd client (always run in `make ci`).
Live tests require a reachable slskd (`make slskd` / CI slskd job) and a
Soulseek login; they skip when the daemon is down or not connected.
"""

from __future__ import annotations

import os
import socket
from typing import Any
from unittest.mock import patch

import pytest
from maya_contracts import QualityTier
from maya_gateway.services.slskd_search import (
    NGGYU_ARTIST,
    NGGYU_TITLE,
    enqueue_download,
    flac_hits,
    is_seven_inch,
    nggyu_7inch_query,
    pick_seven_inch_flac,
    reset_client,
    search_slskd,
)

_SEVEN_FLAC = (
    r"Music\Rick Astley\Never Gonna Give You Up 7inch\01 - Never Gonna Give You Up.flac"
)
_MP3 = r"Music\Rick Astley\Whenever You Need Somebody\01 - Never Gonna Give You Up.mp3"
_ALBUM_FLAC = r"Music\Rick Astley\Whenever You Need Somebody\01 - Never Gonna Give You Up.flac"


class _FakeSearches:
    def __init__(self, files: list[dict[str, Any]]) -> None:
        self.files = files
        self.last_text = ""

    def search_text(self, text: str) -> dict[str, str]:
        self.last_text = text
        return {"id": "search-nggyu"}

    def state(self, search_id: str, includeResponses: bool = False) -> dict[str, Any]:
        assert search_id == "search-nggyu"
        return {
            "responses": [
                {
                    "username": "peer-one",
                    "files": self.files,
                }
            ]
        }


class _FakeTransfers:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []

    def enqueue(self, username: str, payload: list[dict[str, Any]]) -> dict[str, str]:
        self.enqueued.append({"username": username, "payload": payload})
        return {"id": "xfer-7inch"}

    def get_all_downloads(self) -> list[dict[str, Any]]:
        return [{"id": "xfer-7inch", "files": self.enqueued}]


class _FakeClient:
    def __init__(self, files: list[dict[str, Any]]) -> None:
        self.searches = _FakeSearches(files)
        self.transfers = _FakeTransfers()


def _file(filename: str, size: int, *, locked: bool = False) -> dict[str, Any]:
    return {
        "filename": filename,
        "size": size,
        "isLocked": locked,
        "hasFreeUploadSlot": True,
        "queueLength": 0,
        "uploadSpeed": 1_000_000,
    }


def _slskd_listening() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 5030), timeout=0.5):
            return True
    except OSError:
        return False


def _require_live_slskd() -> None:
    if not os.environ.get("SLSKD_API_KEY"):
        pytest.skip("SLSKD_API_KEY is not set")
    if not _slskd_listening():
        pytest.skip("slskd is not listening on 127.0.0.1:5030")


@pytest.fixture(autouse=True)
def _reset_slskd_client() -> None:
    reset_client()
    yield
    reset_client()


def test_nggyu_query_mentions_seven_inch_and_disables_exact_phrase() -> None:
    query = nggyu_7inch_query()
    text = query.to_slskd_text()
    assert NGGYU_ARTIST in text
    assert NGGYU_TITLE in text
    assert '7"' in text
    assert query.exact_phrase is False
    assert query.format_filter is QualityTier.LOSSLESS


def test_is_seven_inch_tokens() -> None:
    assert is_seven_inch(_SEVEN_FLAC)
    assert is_seven_inch('Rick Astley - Never Gonna Give You Up (7").flac')
    assert not is_seven_inch(_ALBUM_FLAC)


def test_search_filters_mp3_and_keeps_flac(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(
        [
            _file(_MP3, 5_000_000),
            _file(_ALBUM_FLAC, 30_000_000),
            _file(_SEVEN_FLAC, 12_000_000),
        ]
    )
    monkeypatch.setattr(
        "maya_gateway.services.slskd_search._get_client", lambda: fake
    )
    monkeypatch.setattr("maya_gateway.services.slskd_search.time.sleep", lambda _s: None)

    result = search_slskd(nggyu_7inch_query(), wait_seconds=0)
    assert fake.searches.last_text
    assert NGGYU_TITLE in fake.searches.last_text
    extensions = {hit.extension for hit in result.hits}
    assert "mp3" not in extensions
    assert "flac" in extensions
    kept = flac_hits(result)
    assert {hit.filename for hit in kept} == {_ALBUM_FLAC, _SEVEN_FLAC}
    picked = pick_seven_inch_flac(result)
    assert picked is not None
    assert picked.filename == _SEVEN_FLAC
    assert picked.extension == "flac"


def test_download_enqueues_seven_inch_flac(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(
        [
            _file(_MP3, 5_000_000),
            _file(_SEVEN_FLAC, 12_000_000),
        ]
    )
    monkeypatch.setattr(
        "maya_gateway.services.slskd_search._get_client", lambda: fake
    )
    monkeypatch.setattr("maya_gateway.services.slskd_search.time.sleep", lambda _s: None)

    result = search_slskd(nggyu_7inch_query(), wait_seconds=0)
    hit = pick_seven_inch_flac(result)
    assert hit is not None
    transfer_id = enqueue_download(hit.username, hit.filename, hit.size)
    assert transfer_id == "xfer-7inch"
    assert fake.transfers.enqueued == [
        {
            "username": "peer-one",
            "payload": [
                {
                    "filename": _SEVEN_FLAC,
                    "size": 12_000_000,
                    "startOffset": 0,
                }
            ],
        }
    ]


@pytest.mark.slskd
@pytest.mark.integration
def test_live_search_filter_and_download_nggyu_7inch() -> None:
    _require_live_slskd()
    wait = int(os.environ.get("SLSKD_SEARCH_WAIT", "25"))
    result = search_slskd(nggyu_7inch_query(), wait_seconds=wait)
    flacs = flac_hits(result)
    if not flacs:
        pytest.skip(f"no FLAC hits for {NGGYU_TITLE!r} (slskd not logged in or empty network)")
    hit = pick_seven_inch_flac(result)
    assert hit is not None
    assert hit.extension == "flac"
    seven = [item for item in flacs if is_seven_inch(item.filename)]
    assert seven, (
        "FLAC hits did not include a 7-inch filename; sample: "
        + ", ".join(item.filename for item in flacs[:5])
    )
    assert is_seven_inch(hit.filename)
    transfer_id = enqueue_download(hit.username, hit.filename, hit.size)
    assert transfer_id, f"enqueue failed for {hit.filename}"
