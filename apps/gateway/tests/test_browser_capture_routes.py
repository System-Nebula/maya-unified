"""Tests for /api/browser/capture routes."""

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

from apps.gateway.browser_capture_routes import router as browser_router  # noqa: E402
from maya_contracts import CaptureManifest  # noqa: E402
from services.auth.deps import require_browser_capture  # noqa: E402
from services.auth.operator_store import get_db_session  # noqa: E402


class _FakeOperator:
    def __init__(self, operator_id: uuid.UUID):
        self.id = operator_id
        self.username = "tester"
        self.role = "admin"
        self.is_active = True
        self.is_banned = False
        self.created_at = datetime.now(timezone.utc)
        self.last_login_at = None


async def _fake_db_session():
    yield None


def _build_app(operator: _FakeOperator | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(browser_router)
    app.dependency_overrides[get_db_session] = _fake_db_session
    app.dependency_overrides[require_browser_capture] = lambda: operator
    return app


def test_capture_requires_auth_without_override() -> None:
    app = FastAPI()
    app.include_router(browser_router)
    app.dependency_overrides[get_db_session] = _fake_db_session
    client = TestClient(app)
    resp = client.post(
        "/api/browser/capture",
        json={
            "capture_type": "article",
            "url": "https://example.com/post",
            "title": "Example",
        },
    )
    assert resp.status_code == 401


def test_capture_200_with_stubbed_service() -> None:
    manifest = CaptureManifest(
        capture_id=str(uuid.uuid4()),
        content_hash="abc123",
        duplicate=False,
        stored_assets=[],
        queued_at=1.0,
    )
    app = _build_app(_FakeOperator(uuid.uuid4()))
    client = TestClient(app)

    with patch("apps.gateway.browser_capture_routes.process_capture", new=AsyncMock(return_value=manifest)):
        resp = client.post(
            "/api/browser/capture",
            headers={"X-Maya-Capture-Token": "test-token"},
            json={
                "capture_type": "article",
                "url": "https://example.com/post",
                "title": "Example Post",
                "reader_text": "Body text",
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["content_hash"] == "abc123"
    assert body["duplicate"] is False


def test_capture_duplicate_manifest() -> None:
    capture_id = str(uuid.uuid4())
    manifest = CaptureManifest(
        capture_id=capture_id,
        content_hash="deadbeef",
        duplicate=True,
        stored_assets=[],
        queued_at=2.0,
    )
    app = _build_app(_FakeOperator(uuid.uuid4()))
    client = TestClient(app)
    with patch("apps.gateway.browser_capture_routes.process_capture", new=AsyncMock(return_value=manifest)):
        resp = client.post(
            "/api/browser/capture",
            json={
                "capture_type": "generic",
                "url": "https://example.com",
            },
        )
    assert resp.status_code == 200
    assert resp.json()["duplicate"] is True
    assert resp.json()["capture_id"] == capture_id
