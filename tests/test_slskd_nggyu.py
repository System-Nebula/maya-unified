"""slskd music-query smoke: search, FLAC filter, Never Gonna Give You Up 7\" download.

Unmarked tests use a fake slskd client (always run in `make ci`).
Live tests require a reachable slskd (`make slskd`). The bundled
maya-dev-example test account drives an in-repo stand-in; a real Soulseek
login in OpenBao uses the live network. Tests skip when the daemon is down.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from maya_contracts import QualityTier, SearchQuery
from maya_gateway.services.slskd_search import (
    NGGYU_ARTIST,
    NGGYU_TITLE,
    enqueue_download,
    flac_hits,
    is_seven_inch,
    is_twelve_inch,
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

    def search_text(self, text: str, **kwargs: Any) -> dict[str, str]:
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


def _search_wait() -> int:
    mode = Path("data/slskd_mode")
    default = "0" if mode.is_file() and mode.read_text(encoding="utf-8").strip() == "example" else "25"
    return int(os.environ.get("SLSKD_SEARCH_WAIT", default))


def _require_live_slskd() -> None:
    if not os.environ.get("SLSKD_API_KEY"):
        key_file = Path("data/slskd_api_key")
        if key_file.is_file():
            os.environ["SLSKD_API_KEY"] = key_file.read_text(encoding="utf-8").strip()
        elif Path("data/slskd_mode").is_file() and Path("data/slskd_mode").read_text(encoding="utf-8").strip() == "example":
            os.environ["SLSKD_API_KEY"] = "ci-cloud-agent-slskd-key"
    if not os.environ.get("SLSKD_API_KEY"):
        pytest.skip("SLSKD_API_KEY is not set")
    if not _slskd_listening():
        pytest.skip("slskd is not listening on 127.0.0.1:5030")


@pytest.fixture(autouse=True)
def _reset_slskd_client() -> None:
    reset_client()
    yield
    reset_client()


def test_nggyu_query_is_artist_title_without_seven_inch_token() -> None:
    query = nggyu_7inch_query()
    text = query.to_slskd_text()
    assert NGGYU_ARTIST in text
    assert NGGYU_TITLE in text
    assert '7"' not in text
    assert "7inch" not in text.lower()
    assert query.exact_phrase is False
    assert query.format_filter is QualityTier.LOSSLESS


def test_is_seven_inch_tokens() -> None:
    assert is_seven_inch(_SEVEN_FLAC)
    assert is_seven_inch('Rick Astley - Never Gonna Give You Up (7").flac')
    assert not is_seven_inch(_ALBUM_FLAC)
    assert is_twelve_inch("Rick Astley - Never Gonna Give You Up (12 Inch) 113.mp3")
    assert not is_twelve_inch(_ALBUM_FLAC)


def test_brat_query_then_flac_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    brat_flac = r"Music\Charli XCX\Brat\01 - 360.flac"
    brat_mp3 = r"Music\Charli XCX\Brat\01 - 360.mp3"
    brat_m4a = r"Music\Charli XCX\Brat\02 - Von dutch.m4a"
    fake = _FakeClient(
        [
            _file(brat_mp3, 4_000_000),
            _file(brat_m4a, 6_000_000),
            _file(brat_flac, 28_000_000),
        ]
    )
    monkeypatch.setattr(
        "maya_gateway.services.slskd_search._get_client", lambda: fake
    )
    monkeypatch.setattr("maya_gateway.services.slskd_search.time.sleep", lambda _s: None)

    query = SearchQuery(
        album="brat",
        exact_phrase=False,
        format_filter=QualityTier.LOSSLESS,
        max_results=50,
    )
    result = search_slskd(query, wait_seconds=0)
    assert "brat" in fake.searches.last_text.lower()
    assert {hit.extension for hit in result.hits} == {"flac"}
    kept = flac_hits(result)
    assert [hit.filename for hit in kept] == [brat_flac]


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


def test_pick_prefers_twelve_inch_over_album_when_no_seven(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    twelve = r"Music\Rick Astley\Never Gonna Give You Up (12 Inch).flac"
    fake = _FakeClient(
        [
            _file(_ALBUM_FLAC, 30_000_000),
            _file(twelve, 14_000_000),
        ]
    )
    monkeypatch.setattr(
        "maya_gateway.services.slskd_search._get_client", lambda: fake
    )
    monkeypatch.setattr("maya_gateway.services.slskd_search.time.sleep", lambda _s: None)
    result = search_slskd(nggyu_7inch_query(), wait_seconds=0)
    picked = pick_seven_inch_flac(result)
    assert picked is not None
    assert picked.filename == twelve


class _DelayedSearches(_FakeSearches):
    def __init__(self, files: list[dict[str, Any]]) -> None:
        super().__init__(files)
        self.calls = 0

    def state(self, search_id: str, includeResponses: bool = False) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            return {
                "isComplete": False,
                "state": "InProgress",
                "fileCount": 12,
                "responseCount": 4,
                "responses": [],
            }
        payload = super().state(search_id, includeResponses=includeResponses)
        payload["isComplete"] = True
        payload["state"] = "Completed"
        return payload


def test_search_polls_until_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient([_file(_SEVEN_FLAC, 12_000_000)])
    fake.searches = _DelayedSearches(fake.searches.files)
    monkeypatch.setattr(
        "maya_gateway.services.slskd_search._get_client", lambda: fake
    )
    monkeypatch.setattr("maya_gateway.services.slskd_search.time.sleep", lambda _s: None)
    result = search_slskd(nggyu_7inch_query(), wait_seconds=5)
    assert fake.searches.calls >= 2
    assert flac_hits(result)


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
    wait = _search_wait()
    result = search_slskd(nggyu_7inch_query(), wait_seconds=wait)
    flacs = flac_hits(result)
    artifact = Path("data/slskd/last_nggyu_search.json")
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(
            {
                "query": result.query.to_slskd_text(),
                "search_id": result.search_id,
                "elapsed_seconds": result.elapsed_seconds,
                "total_hits": result.total_hits,
                "flac": len(flacs),
                "seven_inch": sum(1 for hit in flacs if is_seven_inch(hit.filename)),
                "twelve_inch": sum(1 for hit in flacs if is_twelve_inch(hit.filename)),
                "sample": [hit.filename for hit in flacs[:8]],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if not flacs:
        pytest.skip(
            f"no FLAC hits for {NGGYU_TITLE!r} after {wait}s "
            f"(search_id={result.search_id}; wrote {artifact})"
        )
    hit = pick_seven_inch_flac(result)
    assert hit is not None
    assert hit.extension == "flac"
    transfer_id = enqueue_download(hit.username, hit.filename, hit.size)
    assert transfer_id, f"enqueue failed for {hit.filename}"


@pytest.mark.slskd
@pytest.mark.integration
def test_live_brat_then_flac_filter() -> None:
    _require_live_slskd()
    result = search_slskd(
        SearchQuery(
            album="brat",
            exact_phrase=False,
            format_filter=QualityTier.LOSSLESS,
            max_results=50,
        ),
        wait_seconds=_search_wait(),
    )
    kept = flac_hits(result)
    if not kept:
        pytest.skip("no FLAC hits for brat (slskd not logged in or empty network)")
    assert all(hit.extension.lower() == "flac" for hit in kept)
