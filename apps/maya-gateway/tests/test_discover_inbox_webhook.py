"""Tests for discover inbox webhook."""

from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import hashlib
import hmac
import os
import time

import pytest
from httpx import ASGITransport, AsyncClient

from maya_gateway.main import app
from maya_gateway.routes import discover_inbox as inbox_routes
from maya_gateway.services.mailgun_webhook import reset_replay_cache_for_tests

OLIVIA_HTML = Path(__file__).resolve().parents[1].joinpath(
    "src/maya_gateway/static/demo/olivia-rodrigo-newsletter.html"
).read_text()


@pytest.fixture(autouse=True)
def _mailgun_secret(monkeypatch):
    monkeypatch.setenv("DISCOVER_INBOX_WEBHOOK_SECRET", "test-mailgun-secret")
    reset_replay_cache_for_tests()
    yield
    reset_replay_cache_for_tests()


def _signed_form(**extra) -> dict:
    secret = os.environ["DISCOVER_INBOX_WEBHOOK_SECRET"]
    timestamp = str(int(time.time()))
    token = "test-token-" + timestamp
    signature = hmac.new(
        secret.encode(),
        f"{timestamp}{token}".encode(),
        hashlib.sha256,
    ).hexdigest()
    data = {
        "timestamp": timestamp,
        "token": token,
        "signature": signature,
        **extra,
    }
    return data


@pytest.mark.anyio
async def test_inbox_webhook_stores_knowledge_item(monkeypatch):
    captured: dict = {}

    class FakeSession:
        commits = 0

        async def commit(self) -> None:
            self.commits += 1

    fake_session = FakeSession()

    async def fake_session_dependency():
        yield fake_session

    async def fake_store_html(document: str):
        captured["stored_html"] = document
        return "artifact-test", "discover/artifacts/artifact-test.html"

    async def fake_project(parsed):
        captured["projected"] = parsed.artist_slug
        return None

    async def fake_save(session, parsed, **kwargs):
        assert session is fake_session
        captured["saved"] = parsed.artist_slug
        return SimpleNamespace(
            id=uuid4(),
            source=parsed.source,
            source_kind="email_newsletter",
            artist_slug=parsed.artist_slug,
            artist_display=parsed.artist_display,
            item_type=parsed.item_type.value,
            tags=parsed.tags,
            title=parsed.title,
            track=parsed.track,
            album=parsed.album,
            release_date=parsed.release_date,
            promo=parsed.promo,
            handwritten_note=parsed.handwritten_note,
            html_artifact_key=kwargs["artifact_key"],
            text_fallback=parsed.text_fallback,
            ontology_artist_id=None,
            brand_color=parsed.brand_color,
            received_at=datetime.now(timezone.utc),
            extras=parsed.extras,
        )

    async def fake_notify(*args, **kwargs):
        captured["notified"] = True

    monkeypatch.setattr(inbox_routes, "store_html", fake_store_html)
    monkeypatch.setattr(inbox_routes, "project_to_ontology", fake_project)
    monkeypatch.setattr(inbox_routes, "save_knowledge_item", fake_save)
    monkeypatch.setattr(inbox_routes, "notify_followed_operators", fake_notify)
    app.dependency_overrides[inbox_routes.get_async_session] = fake_session_dependency
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/discover/inbox/webhook",
                data=_signed_form(
                    sender="news@oliviarodrigo.umusic-online.com",
                    From="Olivia Rodrigo <news@oliviarodrigo.umusic-online.com>",
                    subject="New music from Olivia Rodrigo",
                    **{"body-html": OLIVIA_HTML},
                    **{"body-plain": "what's wrong with me ft. Robert Smith"},
                    Date="Sun, 08 Jun 2025 18:12:00 +0000",
                ),
            )
    finally:
        app.dependency_overrides.pop(inbox_routes.get_async_session, None)
    assert resp.status_code == 200
    body = resp.json()
    assert body["artist_slug"] == "olivia-rodrigo"
    assert body["html_artifact_url"].startswith("/api/discover/artifacts/")
    assert captured["saved"] == captured["projected"] == "olivia-rodrigo"
    assert captured["notified"] is True
    assert "<script" not in captured["stored_html"].lower()
    assert fake_session.commits == 1


@pytest.mark.anyio
async def test_inbox_webhook_missing_secret_returns_503(monkeypatch):
    monkeypatch.delenv("DISCOVER_INBOX_WEBHOOK_SECRET", raising=False)
    # Force reload of secret reader via empty env in verify — module reads at call time
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/discover/inbox/webhook",
            data={
                "sender": "a@b.com",
                "subject": "x",
                "body-plain": "hi",
            },
        )
    assert resp.status_code == 503
