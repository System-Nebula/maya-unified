"""End-to-end stub test: play despacito via ontology resolution."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from maya_graph.music.primitives import (
    CanonicalWork,
    Recording,
    SourceRef,
    WorkCandidate,
)


@pytest.mark.asyncio
async def test_resolve_for_play_despacito_wikidata_recording() -> None:
    work = CanonicalWork(
        key="wd:Q130464775",
        label="Despacito",
        anchors=(SourceRef(schema="wd", external_id="Q130464775"),),
    )
    recording = Recording(
        source=SourceRef(schema="yt", external_id="t3IyUATcAbE"),
        title="Despacito",
        webpage_url="https://youtu.be/t3IyUATcAbE",
        duration_seconds=229,
    )

    with (
        patch(
            "services.music.ontology._broker.resolve_work",
            new=AsyncMock(
                return_value=[WorkCandidate(work=work, confidence=0.95, node_id=None)]
            ),
        ),
        patch(
            "services.music.ontology._broker.resolve_recording",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "services.music.ontology._wikidata.fetch_recordings",
            new=AsyncMock(return_value=[recording]),
        ),
        patch(
            "services.music.ontology._broker.ingest",
            new=AsyncMock(return_value="node-uuid"),
        ),
    ):
        from services.music.ontology import resolve_for_play

        resolved = await resolve_for_play("despacito")

    assert resolved is not None
    assert "t3IyUATcAbE" in resolved.play_url
    assert resolved.work_key == "wd:Q130464775"
    assert resolved.title == "Despacito"


@pytest.mark.asyncio
async def test_resolve_for_play_ytdlp_fallback_when_no_wikidata_recording() -> None:
    work = CanonicalWork(key="wd:Q130464775", label="Despacito")
    ytdlp_rec = Recording(
        source=SourceRef(schema="yt", external_id="abc12345678"),
        title="Despacito",
        webpage_url="https://youtu.be/abc12345678",
        attrs={"source": "ytdlp"},
    )

    with (
        patch(
            "services.music.ontology._broker.resolve_work",
            new=AsyncMock(
                return_value=[WorkCandidate(work=work, confidence=0.9, node_id=None)]
            ),
        ),
        patch(
            "services.music.ontology._broker.resolve_recording",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "services.music.ontology._wikidata.fetch_recordings",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "services.music.ontology._ytdlp_recording_for_label",
            new=AsyncMock(return_value=ytdlp_rec),
        ) as ytdlp_mock,
        patch(
            "services.music.ontology._broker.ingest",
            new=AsyncMock(return_value="node-uuid"),
        ),
    ):
        from services.music.ontology import resolve_for_play

        resolved = await resolve_for_play("despacito")

    ytdlp_mock.assert_awaited_once()
    assert resolved is not None
    assert "abc12345678" in resolved.play_url
