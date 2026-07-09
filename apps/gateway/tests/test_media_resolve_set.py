"""Tests for /api/media/resolve live-set artifact shape."""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from apps.gateway.music_routes import router as media_router  # noqa: E402
from services.auth.deps import require_operator  # noqa: E402
from services.auth.operator_store import get_db_session  # noqa: E402
from services.auth.session import OPERATOR_SESSION_COOKIE, sign_operator_session  # noqa: E402
from tests.helpers.music_set_fixtures import ANDREA_URL, andrea_resolved_set  # noqa: E402


@dataclass
class FakeOperator:
    id: uuid.UUID
    username: str = "admin"
    display_name: str = "Admin"
    password_hash: str = "x"
    role: str = "admin"
    avatar_color: str = "#0a84ff"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_login: datetime | None = None
    is_banned: bool = False


def _media_app() -> FastAPI:
    app = FastAPI()
    app.include_router(media_router)

    async def fake_session() -> AsyncGenerator[object, None]:
        class _Session:
            async def commit(self) -> None:
                return None

        yield _Session()

    app.dependency_overrides[get_db_session] = fake_session
    app.dependency_overrides[require_operator] = lambda: FakeOperator(id=uuid.uuid4())
    return app


def test_media_resolve_set_presentation(monkeypatch):
    resolved = andrea_resolved_set()

    async def fake_build(query: str):
        from services.music.set_playlist import build_playlist_from_set

        return build_playlist_from_set(query, resolved)

    monkeypatch.setattr("services.music.ontology.resolve_for_play", AsyncMock(return_value=None))
    monkeypatch.setattr("services.dashboard.player.build_playlist_for_query", fake_build)

    app = _media_app()
    client = TestClient(app)
    token = sign_operator_session(str(uuid.uuid4()))
    client.cookies.set(OPERATOR_SESSION_COOKIE, token)
    resp = client.post("/api/media/resolve", json={"query": ANDREA_URL})
    assert resp.status_code == 200
    data = resp.json()
    assert data["presentation"] == "set"
    assert data["mode"] == "live_set"
    assert data["video_id"] == "u1NHX9FcHVw"
    assert len(data["entries"]) == 26
    assert len(data["tracks"]) == 26
    assert data["entries"][0]["start_seconds"] == 0
    entry9 = data["entries"][8]
    assert entry9["position"] == 9
    assert entry9["label"] == "Vall Du Son - Play"
    assert entry9["artist"] == "Vall Du Son"
    assert entry9["title"] == "Play"
    assert data["title"] == resolved.title
