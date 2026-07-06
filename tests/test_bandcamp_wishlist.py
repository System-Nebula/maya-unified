"""Bandcamp wishlist integration tests."""

from __future__ import annotations

import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.paths import setup_paths

setup_paths()

from services.integrations.bandcamp.client import (  # noqa: E402
    BandcampProfileNotFound,
    fetch_wishlist_items,
    normalize_wishlist_item,
    resolve_fan_profile,
)
from services.integrations.bandcamp.service import (  # noqa: E402
    bandcamp_playback_intent,
    expand_filter_keywords,
    format_wishlist_speech,
    is_bandcamp_wishlist_turn,
    item_matches_filter,
    list_wishlist,
    parse_bandcamp_username,
    play_wishlist,
    resolve_username,
)


def _profile_html(blob: dict) -> str:
    encoded = json.dumps(blob).replace('"', "&quot;")
    return f'<html><div id="pagedata" data-blob="{encoded}"></div></html>'


PROFILE_BLOB = {
    "fan_data": {"fan_id": 424242, "name": "King Myles"},
    "wishlist_data": {"item_count": 888, "private": False, "last_token": "1::a::"},
}


class FakeResponse:
    def __init__(self, *, status_code: int = 200, text: str = "", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json = json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class FakeClient:
    def __init__(self, *, profile_html: str | None = None, wishlist_items: list | None = None):
        self.profile_html = profile_html or _profile_html(PROFILE_BLOB)
        self.wishlist_items = wishlist_items or [
            {
                "album_title": "Test Album",
                "band_name": "Test Artist",
                "item_url": "https://x.bandcamp.com/album/test",
                "item_type": "a",
            }
        ]

    def get(self, url: str) -> FakeResponse:
        if "notfound" in url:
            return FakeResponse(status_code=404)
        return FakeResponse(text=self.profile_html)

    def post(self, url: str, json: dict | None = None, headers=None) -> FakeResponse:
        _ = url, json, headers
        return FakeResponse(json_data={"items": self.wishlist_items})

    def close(self) -> None:
        pass


def test_resolve_fan_profile_extracts_fan_id():
    profile = resolve_fan_profile("king_myles", client=FakeClient())
    assert profile["fan_id"] == 424242
    assert profile["wishlist_count"] == 888
    assert profile["username"] == "king_myles"


def test_resolve_fan_profile_not_found():
    with pytest.raises(BandcampProfileNotFound):
        resolve_fan_profile("notfound", client=FakeClient())


def test_fetch_wishlist_items_parses_items():
    items = fetch_wishlist_items(424242, count=5, client=FakeClient())
    assert len(items) == 1
    assert items[0]["album_title"] == "Test Album"


def test_normalize_wishlist_item():
    item = normalize_wishlist_item(
        {"album_title": "Half Life", "band_name": "Dom & Roland", "item_url": "https://a/album/h", "item_type": "a"}
    )
    assert item["title"] == "Half Life"
    assert item["artist"] == "Dom & Roland"
    assert item["item_type"] == "album"


def test_list_wishlist_returns_slice():
    with patch(
        "services.integrations.bandcamp.service.resolve_fan_profile",
        return_value={
            "username": "king_myles",
            "fan_id": 1,
            "display_name": "King Myles",
            "wishlist_count": 888,
            "wishlist_private": False,
        },
    ), patch(
        "services.integrations.bandcamp.service.fetch_wishlist_items",
        return_value=[
            {"album_title": "A", "band_name": "B", "item_url": "https://x", "item_type": "a"},
        ],
    ):
        result = list_wishlist("king_myles", limit=1, offset=0)
    assert result["total_count"] == 888
    assert len(result["items"]) == 1
    assert result["items"][0]["title"] == "A"


def test_format_wishlist_speech():
    text = format_wishlist_speech(
        {
            "total_count": 888,
            "offset": 0,
            "items": [{"title": "DJ-Kicks", "artist": "Jessy Lanza"}],
        }
    )
    assert "888" in text
    assert "Jessy Lanza" in text
    assert "DJ-Kicks" in text


def test_resolve_username_prefers_settings():
    assert resolve_username({"bandcamp": {"username": "king_myles", "enabled": True}}) == "king_myles"


def test_resolve_username_env_fallback(monkeypatch):
    monkeypatch.setenv("MAYA_BANDCAMP_USERNAME", "env_user")
    assert resolve_username({}) == "env_user"


def test_parse_bandcamp_username_from_wishlist_url():
    assert parse_bandcamp_username("https://bandcamp.com/king_myles/wishlist") == "king_myles"
    assert parse_bandcamp_username("bandcamp.com/king_myles") == "king_myles"


def test_resolve_username_from_url_hint():
    assert resolve_username({}, hint="https://bandcamp.com/king_myles/wishlist") == "king_myles"


def test_is_bandcamp_wishlist_turn_and_playback_intent():
    assert is_bandcamp_wishlist_turn("queue dnb from my bandcamp wishlist")
    assert bandcamp_playback_intent("queue dnb from my bandcamp wishlist")
    assert is_bandcamp_wishlist_turn("https://bandcamp.com/king_myles/wishlist")


def test_item_matches_filter_dnb_keywords():
    keywords = expand_filter_keywords("dnb")
    assert item_matches_filter({"title": "Jungle Massive", "artist": "DJ Foo"}, keywords)
    assert not item_matches_filter({"title": "Ambient Drone", "artist": "Calm"}, keywords)


def test_play_wishlist_builds_playlist(monkeypatch):
    catalog = {
        "username": "king_myles",
        "items": [
            {"title": "Jungle EP", "artist": "A", "url": "https://a.bandcamp.com/album/jungle"},
            {"title": "Ambient", "artist": "B", "url": "https://b.bandcamp.com/album/calm"},
        ],
    }

    class FakeExpansion:
        title = "Jungle EP"
        tracks = [("https://a.bandcamp.com/track/1", "Track 1")]

    with patch("services.integrations.bandcamp.service.list_wishlist", return_value=catalog), patch(
        "services.discord.playlist.expand_playlist", return_value=FakeExpansion()
    ):
        result = play_wishlist("king_myles", filter_text="dnb", limit=2)

    assert result["ok"] is True
    assert result["queued"] == 1
    assert result["playlist"]["tracks"]


def test_bandcamp_read_wishlist_tool_from_url_hint():
    from tools.bandcamp import build_bandcamp_tools

    tools = build_bandcamp_tools()
    spec = next(t for t in tools if t.name == "bandcamp_read_wishlist")
    mock_hub = MagicMock()
    mock_hub._active_operator_id = "op-1"
    mock_hub._last_user_text = "https://bandcamp.com/king_myles/wishlist"
    fake_result = {
        "username": "king_myles",
        "total_count": 1,
        "offset": 0,
        "items": [{"title": "A", "artist": "B"}],
    }

    def fake_run_sync(coro, *, timeout=120):
        coro.close()
        return fake_result

    with patch("services.voice.hub.hub", mock_hub), patch(
        "services.settings.store.load_effective_settings",
        return_value={"bandcamp": {"username": "", "enabled": True}},
    ), patch("services.integrations.bandcamp.config.default_username", return_value=""), patch(
        "services.integrations.bandcamp.ensure_username_configured"
    ), patch("services.async_bridge.run_sync", side_effect=fake_run_sync):
        result = spec.handler({})

    assert result["ok"] is True
    assert result["username"] == "king_myles"


def test_bandcamp_read_wishlist_tool_missing_username():
    from tools.bandcamp import build_bandcamp_tools

    tools = build_bandcamp_tools()
    spec = next(t for t in tools if t.name == "bandcamp_read_wishlist")
    mock_hub = MagicMock()
    mock_hub._active_operator_id = None
    mock_hub._last_user_text = ""
    with patch("services.voice.hub.hub", mock_hub), patch(
        "services.settings.store.load_effective_settings",
        return_value={"bandcamp": {"username": "", "enabled": True}},
    ), patch("services.integrations.bandcamp.config.default_username", return_value=""):
        result = spec.handler({})
    assert result["ok"] is False
    assert "not found" in result["error"].lower()


def test_bandcamp_read_wishlist_tool_success():
    from tools.bandcamp import build_bandcamp_tools

    tools = build_bandcamp_tools()
    spec = next(t for t in tools if t.name == "bandcamp_read_wishlist")
    mock_hub = MagicMock()
    mock_hub._active_operator_id = "op-1"
    fake_result = {
        "username": "king_myles",
        "total_count": 2,
        "offset": 0,
        "items": [{"title": "A", "artist": "B"}],
    }
    def fake_run_sync(coro, *, timeout=120):
        coro.close()
        return fake_result

    with patch("services.voice.hub.hub", mock_hub), patch(
        "services.settings.store.load_effective_settings",
        return_value={"bandcamp": {"username": "king_myles", "enabled": True}},
    ), patch("services.async_bridge.run_sync", side_effect=fake_run_sync):
        result = spec.handler({"limit": 5})
    assert result["ok"] is True
    assert "A" in result["message"]
    assert result["total"] == 2


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


@pytest.fixture
def fake_operator() -> FakeOperator:
    return FakeOperator(id=uuid.uuid4())


@pytest.fixture
def bandcamp_client(fake_operator: FakeOperator) -> TestClient:
    from apps.gateway.bandcamp_integrations_routes import router as bandcamp_router
    from services.auth.deps import require_operator
    from services.auth.session import OPERATOR_SESSION_COOKIE, sign_operator_session

    app = FastAPI()
    app.include_router(bandcamp_router)

    async def _op() -> FakeOperator:
        return fake_operator

    app.dependency_overrides[require_operator] = _op
    token = sign_operator_session(str(fake_operator.id))
    client = TestClient(app)
    client.cookies.set(OPERATOR_SESSION_COOKIE, token)
    return client


def test_bandcamp_status_route_unconfigured(bandcamp_client: TestClient):
    with patch(
        "apps.gateway.bandcamp_integrations_routes.load_effective_settings",
        return_value={"bandcamp": {"username": "", "enabled": True}},
    ), patch(
        "apps.gateway.bandcamp_integrations_routes.resolve_username",
        return_value="",
    ):
        resp = bandcamp_client.get("/api/integrations/bandcamp/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is False


def test_bandcamp_status_route_connected(bandcamp_client: TestClient):
    with patch(
        "apps.gateway.bandcamp_integrations_routes.load_effective_settings",
        return_value={"bandcamp": {"username": "king_myles", "enabled": True}},
    ), patch(
        "apps.gateway.bandcamp_integrations_routes.resolve_username",
        return_value="king_myles",
    ), patch(
        "apps.gateway.bandcamp_integrations_routes.connection_status",
        return_value={
            "connected": True,
            "username": "king_myles",
            "wishlist_count": 888,
            "display_name": "King Myles",
        },
    ):
        resp = bandcamp_client.get("/api/integrations/bandcamp/status")
    assert resp.status_code == 200
    assert resp.json()["wishlist_count"] == 888


def test_chat_emit_tags_tool_events_with_corr_id():
    from services.voice.hub import VoiceHub, _chat_event

    hub = VoiceHub()
    captured: list[dict] = []
    hub.broadcast = lambda event, **kwargs: captured.append(event)  # type: ignore[method-assign]

    corr_id = "c_test"
    reply_message_id = "m_reply"

    def _emit_chat(**ev: object) -> None:
        payload = dict(ev)
        ev_type = str(payload.get("type") or "")
        if payload.get("type") == "ai":
            payload = _chat_event(payload, corr_id=corr_id, message_id=reply_message_id)
        elif payload.get("type") in {"status", "delivery"}:
            payload = _chat_event(payload, corr_id=corr_id)
        elif payload.get("type") in {"tool_start", "tool_end", "tool_trace"}:
            payload = _chat_event(payload, corr_id=corr_id)
        hub.broadcast(payload, operator_id="op-1")

    _emit_chat(type="tool_start", tool="bandcamp_play_wishlist", args={"filter": "dnb"})
    assert captured[0]["type"] == "tool_start"
    assert captured[0]["corr_id"] == corr_id
