"""Live catalog mapping for Brat CD + Never Gonna Give You Up (network)."""

from __future__ import annotations

import os

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slskd]


@pytest.mark.asyncio
async def test_live_catalog_maps_brat_and_nggyu(tmp_path, monkeypatch) -> None:
    if os.environ.get("CATALOG_LIVE") != "1" and not os.environ.get("SLSKD_API_KEY"):
        pytest.skip("set CATALOG_LIVE=1 to hit MusicBrainz/Discogs/iTunes/Wikidata")

    from scripts.catalog_live_probe import probe

    monkeypatch.setenv(
        "MAYA_ONTOLOGY_DSN",
        os.environ.get("MAYA_ONTOLOGY_DSN")
        or "postgresql://postgres:postgres@localhost:5432/maya_public",
    )
    payload = await probe()
    brat = payload["mapped"]["brat"]
    album = payload["mapped"]["brat_album"]
    nggyu = payload["mapped"]["nggyu"]
    assert brat["label"]
    assert nggyu["label"]
    assert "Astley" in (nggyu["artists"] or nggyu["label"])
    nggyu_schemas = {row["schema"] for row in nggyu["anchors"]}
    brat_hits = payload["hits"]["brat_cd"]
    assert any(row["ok"] for row in brat_hits), "Brat CD missed every album catalog"
    assert any(
        row["provider"] == "apple_music" and row["ok"] for row in brat_hits
    ), "Brat CD missed Apple Music album"
    assert nggyu_schemas, "NGGYU mapped with no catalog anchors"
    assert not album["key"].startswith("fp:"), album
    (tmp_path / "catalog_live.json").write_text(__import__("json").dumps(payload["markdown"]))
