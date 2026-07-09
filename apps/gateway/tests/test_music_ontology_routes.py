"""Tests for /api/music/ontology routes."""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from apps.gateway.music_ontology_routes import router as ontology_router  # noqa: E402
from maya_contracts import TrackMetadata, SourceRefModel  # noqa: E402
from services.auth.deps import require_operator  # noqa: E402
from services.auth.operator_store import get_db_session  # noqa: E402
from services.auth.session import OPERATOR_SESSION_COOKIE, sign_operator_session  # noqa: E402


class _FakeOperator:
    def __init__(self, operator_id: uuid.UUID):
        self.id = operator_id
        self.username = "tester"
        self.role = "admin"
        self.is_active = True
        self.created_at = datetime.now(timezone.utc)
        self.last_login_at = None


async def _fake_db_session():
    yield None


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(ontology_router)
    app.dependency_overrides[get_db_session] = _fake_db_session
    app.dependency_overrides[require_operator] = lambda: _FakeOperator(uuid.uuid4())
    return app


def test_lookup_requires_operator_without_override() -> None:
    app = FastAPI()
    app.include_router(ontology_router)
    app.dependency_overrides[get_db_session] = _fake_db_session
    client = TestClient(app)
    resp = client.get("/api/music/ontology/lookup", params={"q": "M83 Midnight City"})
    assert resp.status_code == 401


def test_lookup_200_with_stubbed_service() -> None:
    meta = TrackMetadata(
        title="Midnight City",
        artist="M83",
        work_key="wd:Q1",
        source_refs=[SourceRefModel(schema_id="wd", external_id="Q1")],
        confidence=0.9,
    )
    app = _build_app()
    client = TestClient(app)
    oid = uuid.uuid4()
    token = sign_operator_session(str(oid))
    with patch("services.music.ontology.lookup", new=AsyncMock(return_value=meta)):
        resp = client.get(
            "/api/music/ontology/lookup",
            params={"q": "M83 Midnight City"},
            cookies={OPERATOR_SESSION_COOKIE: token},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Midnight City"
    assert body["work_key"] == "wd:Q1"


def test_lookup_404_when_no_match() -> None:
    app = _build_app()
    client = TestClient(app)
    with patch("services.music.ontology.lookup", new=AsyncMock(return_value=None)):
        resp = client.get("/api/music/ontology/lookup", params={"q": "unknown xyz"})
    assert resp.status_code == 404


def test_index_url_400_for_unsupported() -> None:
    app = _build_app()
    client = TestClient(app)
    resp = client.post("/api/music/url/index", json={"url": "https://example.com/not-music"})
    assert resp.status_code == 400


def test_index_url_200_fred_again_merged_set() -> None:
    _TESTS = Path(__file__).resolve().parents[3] / "tests"
    if str(_TESTS) not in sys.path:
        sys.path.insert(0, str(_TESTS))

    from helpers.music_set_fixtures import FRED_AGAIN_1001TL_URL, fred_again_merged_resolved_set

    merged = fred_again_merged_resolved_set()
    app = _build_app()
    client = TestClient(app)
    with patch(
        "services.music.url_handler.index_music_url",
        new=AsyncMock(return_value=merged),
    ):
        resp = client.post(
            "/api/music/url/index",
            json={"url": FRED_AGAIN_1001TL_URL, "correlate": True},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["set_key"] == merged.set_key
    assert len(body["entries"]) == 3
    assert len(body["linked_sets"]) >= 2
    first_refs = {r["schema_id"] for r in body["entries"][0]["source_refs"]}
    assert first_refs == {"yt", "1001tl", "apple_music"}

