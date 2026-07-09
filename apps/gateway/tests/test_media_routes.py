"""Tests for the /api/media/stream music proxy route."""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from apps.gateway import music_routes  # noqa: E402
from apps.gateway.music_routes import router as media_router  # noqa: E402
from services.auth.deps import require_operator  # noqa: E402
from services.auth.operator_store import get_db_session  # noqa: E402
from services.auth.session import OPERATOR_SESSION_COOKIE, sign_operator_session  # noqa: E402


class _FakeStdout:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def read(self, _n):
        return self._chunks.pop(0) if self._chunks else b""

    def close(self):
        pass


class _FakePopen:
    def __init__(self, cmd, **_kw):
        # ffmpeg (second stage) yields the audio bytes; yt-dlp stdout is drained.
        is_ffmpeg = "ffmpeg" in str(cmd[0])
        self.stdout = _FakeStdout([b"ID3audio-bytes"] if is_ffmpeg else [])

    def poll(self):
        return 0

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


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


def _media_app(*, authed: bool) -> FastAPI:
    app = FastAPI()
    app.include_router(media_router)

    async def fake_session() -> AsyncGenerator[object, None]:
        class _Session:
            async def commit(self) -> None:
                return None

        yield _Session()

    app.dependency_overrides[get_db_session] = fake_session

    if authed:
        op = FakeOperator(id=uuid.uuid4())

        async def fake_require_operator():
            return op

        app.dependency_overrides[require_operator] = fake_require_operator

    return app


def test_stream_requires_operator():
    app = _media_app(authed=False)
    client = TestClient(app)
    resp = client.get("/api/media/stream", params={"q": "https://x.bandcamp.com/track/a"})
    assert resp.status_code == 401


def test_stream_with_cookie_auth(monkeypatch):
    app = _media_app(authed=True)
    monkeypatch.setattr(music_routes.shutil, "which", lambda _name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(music_routes.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr("services.discord.youtube_patch._extractor_args_cli", lambda: [])
    monkeypatch.setattr("services.discord.youtube_patch._cookie_cli_args", lambda: [])

    client = TestClient(app)
    token = sign_operator_session(str(uuid.uuid4()))
    client.cookies.set(OPERATOR_SESSION_COOKIE, token)
    resp = client.get("/api/media/stream", params={"q": "https://x.bandcamp.com/track/a"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    assert resp.content == b"ID3audio-bytes"


def test_stream_pipes_audio(monkeypatch):
    app = _media_app(authed=True)
    monkeypatch.setattr(music_routes.shutil, "which", lambda _name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(music_routes.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr("services.discord.youtube_patch._extractor_args_cli", lambda: [])
    monkeypatch.setattr("services.discord.youtube_patch._cookie_cli_args", lambda: [])

    client = TestClient(app)
    resp = client.get("/api/media/stream", params={"q": "https://x.bandcamp.com/track/a"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    assert resp.content == b"ID3audio-bytes"


def test_meta_requires_operator():
    app = _media_app(authed=False)
    client = TestClient(app)
    resp = client.get("/api/media/meta", params={"q": "some song"})
    assert resp.status_code == 401


def test_meta_returns_metadata(monkeypatch):
    music_routes._META_CACHE.clear()
    app = _media_app(authed=True)
    meta = {
        "title": "Song Title",
        "artist": "The Artist",
        "thumbnail": "https://img.example/cover.jpg",
        "duration": 214.0,
    }
    monkeypatch.setattr(music_routes, "_extract_meta", lambda _target: dict(meta))

    client = TestClient(app)
    resp = client.get("/api/media/meta", params={"q": "the artist song title"})
    assert resp.status_code == 200
    assert resp.json() == meta


def test_meta_failure_returns_empty(monkeypatch):
    music_routes._META_CACHE.clear()
    app = _media_app(authed=True)

    def _boom(_target):
        raise RuntimeError("yt-dlp exploded")

    monkeypatch.setattr(music_routes, "_extract_meta", _boom)

    client = TestClient(app)
    resp = client.get("/api/media/meta", params={"q": "broken track"})
    assert resp.status_code == 200
    assert resp.json() == {"title": "", "artist": "", "thumbnail": "", "duration": None}


def test_meta_is_cached(monkeypatch):
    music_routes._META_CACHE.clear()
    app = _media_app(authed=True)
    calls = {"n": 0}

    def _counting(_target):
        calls["n"] += 1
        return {"title": "T", "artist": "A", "thumbnail": "", "duration": None}

    monkeypatch.setattr(music_routes, "_extract_meta", _counting)

    client = TestClient(app)
    client.get("/api/media/meta", params={"q": "same query"})
    client.get("/api/media/meta", params={"q": "same query"})
    assert calls["n"] == 1


def test_cast_requires_operator():
    app = _media_app(authed=False)
    client = TestClient(app)
    assert client.get("/api/media/cast").status_code == 401
    assert client.post("/api/media/cast").status_code == 401
    assert client.delete("/api/media/cast").status_code == 401
    assert client.get("/api/media/player").status_code == 401
    assert client.post("/api/media/player/clear").status_code == 401


def test_player_snapshot_empty(monkeypatch):
    app = _media_app(authed=True)
    monkeypatch.setattr("services.dashboard.player.player_snapshot", lambda _oid: None)
    client = TestClient(app)
    resp = client.get("/api/media/player")
    assert resp.status_code == 404


def test_player_snapshot_returns_playlist(monkeypatch):
    app = _media_app(authed=True)
    snapshot = {
        "type": "playlist",
        "presentation": "set",
        "tracks": [{"title": "A", "query": "https://youtu.be/x", "src": "/api/media/stream?q=x"}],
        "current": 0,
    }

    monkeypatch.setattr("services.dashboard.player.player_snapshot", lambda _oid: snapshot)
    client = TestClient(app)
    resp = client.get("/api/media/player")
    assert resp.status_code == 200
    body = resp.json()
    assert body["presentation"] == "set"
    assert len(body["tracks"]) == 1


def test_player_clear_ok(monkeypatch):
    app = _media_app(authed=True)
    cleared: dict[str, bool] = {"called": False}

    def _clear(*, operator_id: str | None = None):
        cleared["called"] = True
        assert operator_id

    monkeypatch.setattr("services.dashboard.player.clear_player_and_broadcast", _clear)
    client = TestClient(app)
    resp = client.post("/api/media/player/clear")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert cleared["called"] is True


def test_cast_start_without_snapshot(monkeypatch):
    app = _media_app(authed=True)

    async def _start(**_kwargs):
        raise ValueError("Nothing in the dashboard player to cast.")

    monkeypatch.setattr("services.dashboard.discord_cast.start_cast", _start)

    client = TestClient(app)
    resp = client.post("/api/media/cast")
    assert resp.status_code == 400
    assert "dashboard player" in resp.json()["detail"].lower()


def test_cast_status_unavailable(monkeypatch):
    app = _media_app(authed=True)

    async def _status(**_kwargs):
        return {"available": False, "casting": False, "reason": "offline"}

    monkeypatch.setattr("services.dashboard.discord_cast.cast_status", _status)

    client = TestClient(app)
    resp = client.get("/api/media/cast")
    assert resp.status_code == 200
    assert resp.json()["available"] is False
