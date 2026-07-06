"""Tests for WikidataSchema recording enrichment (P1651 / P1552)."""

from __future__ import annotations

import json

import httpx
import pytest

from maya_graph.music.primitives import CanonicalWork, SourceRef
from maya_graph.music.schemas.wikidata import WikidataSchema


def _claims_response(entity_id: str, claims: dict) -> dict:
    return {"claims": {entity_id: claims}}


def _entities_response(entities: dict) -> dict:
    return {"entities": entities}


class _MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, handlers):
        self._handlers = handlers

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        action = params.get("action", "")
        handler = self._handlers.get(action)
        if handler is None:
            return httpx.Response(404, json={})
        payload = handler(params)
        return httpx.Response(200, json=payload)


@pytest.fixture()
def despacito_client() -> httpx.AsyncClient:
    char_qid = "Q999000001"

    def wbgetentities(params):
        ids = params.get("ids", "")
        if ids == "Q130464775":
            return _entities_response(
                {
                    "Q130464775": {
                        "id": "Q130464775",
                        "claims": {
                            "P1552": [
                                {
                                    "mainsnak": {
                                        "datavalue": {
                                            "type": "wikibase-entityid",
                                            "value": {"id": char_qid},
                                        }
                                    }
                                }
                            ],
                        },
                    }
                }
            )
        if ids == char_qid:
            return _entities_response(
                {
                    char_qid: {
                        "id": char_qid,
                        "labels": {"en": {"value": "YouTube auto-generated video"}},
                        "claims": {
                            "P1651": [
                                {
                                    "mainsnak": {
                                        "datavalue": {
                                            "type": "string",
                                            "value": "t3IyUATcAbE",
                                        }
                                    }
                                }
                            ],
                            "P2047": [
                                {
                                    "mainsnak": {
                                        "datavalue": {
                                            "type": "quantity",
                                            "value": {"amount": "+229.0"},
                                        }
                                    }
                                }
                            ],
                            "P5436": [
                                {
                                    "mainsnak": {
                                        "datavalue": {
                                            "type": "quantity",
                                            "value": {"amount": "+4127158"},
                                        }
                                    }
                                }
                            ],
                        },
                    }
                }
            )
        return _entities_response({})

    transport = _MockTransport({"wbgetentities": wbgetentities})
    return httpx.AsyncClient(transport=transport)


@pytest.mark.asyncio
async def test_fetch_recordings_p1552_to_p1651(despacito_client: httpx.AsyncClient) -> None:
    schema = WikidataSchema(client=despacito_client)
    work = CanonicalWork(
        key="wd:Q130464775",
        label="Despacito",
        anchors=(SourceRef(schema="wd", external_id="Q130464775"),),
    )
    recordings = await schema.fetch_recordings(work)
    assert len(recordings) == 1
    assert recordings[0].source.schema == "yt"
    assert recordings[0].source.external_id == "t3IyUATcAbE"
    assert recordings[0].webpage_url == "https://youtu.be/t3IyUATcAbE"
    assert recordings[0].duration_seconds == 229


@pytest.mark.asyncio
async def test_fetch_recording_by_wd_ref(despacito_client: httpx.AsyncClient) -> None:
    schema = WikidataSchema(client=despacito_client)
    rec = await schema.fetch_recording(SourceRef(schema="wd", external_id="Q130464775"))
    assert rec is not None
    assert rec.source.external_id == "t3IyUATcAbE"
