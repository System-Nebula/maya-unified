"""slskd ingest uses parsed catalog names, never the Soulseek username."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from maya_graph.music.normalize import artist_refs
from maya_graph.music.primitives import CanonicalWork, SourceRef
from services.music.ontology import ingest_slskd_file

_SEVEN = r"Music\Rick Astley\Never Gonna Give You Up 7inch\01 - Never Gonna Give You Up.flac"


@pytest.mark.asyncio
async def test_ingest_slskd_maps_catalog_and_skips_peer_username() -> None:
    mapped = CanonicalWork(
        key="mb:recording/abc",
        label="Never Gonna Give You Up",
        artists=artist_refs("Rick Astley"),
        anchors=(
            SourceRef(schema="mb", external_id="recording/abc"),
            SourceRef(schema="discogs", external_id="master/96559"),
        ),
        attrs={"album": "Whenever You Need Somebody", "base_title": "Never Gonna Give You Up"},
    )
    ingest = AsyncMock(return_value="node-1")
    with patch("services.music.ontology.map_identity", AsyncMock(return_value=mapped)):
        with patch("services.music.ontology._broker") as broker:
            broker.schemas = []
            broker.ingest = ingest
            await ingest_slskd_file(
                username="some-soulseek-peer",
                filename=_SEVEN,
                attrs={"size": 64, "verified": True},
            )
    ingest.assert_awaited_once()
    event = ingest.await_args.args[0]
    assert event.work.label == "Never Gonna Give You Up"
    assert event.work.artists[0].name == "Rick Astley"
    assert event.work.artists[0].name != "some-soulseek-peer"
    rec = event.recordings[0]
    assert rec.source.schema == "slskd"
    assert rec.source.external_id != f"some-soulseek-peer:{_SEVEN}"
    assert rec.attrs["username"] == "some-soulseek-peer"
    assert rec.attrs["filename"] == _SEVEN
    assert any(a.schema == "discogs" for a in event.work.anchors)


@pytest.mark.asyncio
async def test_ingest_slskd_skips_when_path_has_no_artist() -> None:
    ingest = AsyncMock()
    with patch("services.music.ontology._broker") as broker:
        broker.ingest = ingest
        await ingest_slskd_file(username="peer-one", filename=r"shared\01 - untitled.flac")
    ingest.assert_not_called()
