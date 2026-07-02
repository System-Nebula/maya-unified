"""Google integration route and scope tests."""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.paths import setup_paths

setup_paths()

from apps.gateway.google_integrations_routes import router as google_router  # noqa: E402
from services.auth.deps import require_operator  # noqa: E402
from services.auth.operator_store import get_db_session  # noqa: E402
from services.auth.session import OPERATOR_SESSION_COOKIE, sign_operator_session  # noqa: E402
from services.integrations.google.scopes import (  # noqa: E402
    connect_scopes,
    granted_permissions,
    has_permission,
    scopes_for_permissions,
)


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
def google_app() -> FastAPI:
    app = FastAPI()
    app.include_router(google_router)

    async def fake_session() -> AsyncGenerator[object, None]:
        class _Session:
            async def commit(self) -> None:
                return None

            async def flush(self) -> None:
                return None

            def add(self, _obj) -> None:
                return None

            async def execute(self, _q):
                class _R:
                    def scalar_one_or_none(self):
                        return None

                return _R()

        yield _Session()

    app.dependency_overrides[get_db_session] = fake_session
    return app


@pytest.fixture
def authed_google_app(google_app: FastAPI, fake_operator: FakeOperator) -> FastAPI:
    async def fake_require_operator():
        return fake_operator

    google_app.dependency_overrides[require_operator] = fake_require_operator
    return google_app


@pytest.fixture
def authed_client(authed_google_app: FastAPI, fake_operator: FakeOperator) -> TestClient:
    client = TestClient(authed_google_app)
    token = sign_operator_session(str(fake_operator.id))
    client.cookies.set(OPERATOR_SESSION_COOKIE, token)
    return client


def test_scopes_for_permissions_mailbox_read() -> None:
    scopes = scopes_for_permissions(["mailbox_read"])
    assert "https://www.googleapis.com/auth/gmail.readonly" in scopes


def test_connect_scopes_includes_base() -> None:
    scopes = connect_scopes(["mailbox_read", "calendar_read"])
    assert "openid" in scopes
    assert any("gmail" in s for s in scopes)
    assert any("calendar" in s for s in scopes)


def test_granted_permissions_detection() -> None:
    perms = granted_permissions(
        [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/calendar.readonly",
        ]
    )
    assert perms["mailbox_read"] is True
    assert perms["calendar_read"] is True
    assert perms["mailbox_send"] is False


def test_has_permission_calendar_write() -> None:
    assert has_permission(
        ["https://www.googleapis.com/auth/calendar"],
        "calendar_write",
    )
    assert not has_permission(
        ["https://www.googleapis.com/auth/calendar.readonly"],
        "calendar_write",
    )


def test_google_status_requires_auth(google_app: FastAPI) -> None:
    client = TestClient(google_app)
    res = client.get("/api/integrations/google/status")
    assert res.status_code == 401


def test_google_status_disconnected(authed_client: TestClient) -> None:
    with patch(
        "apps.gateway.google_integrations_routes.connection_status",
        return_value={"connected": False, "permissions": {}},
    ):
        res = authed_client.get("/api/integrations/google/status")
    assert res.status_code == 200
    assert res.json()["connected"] is False


def test_google_connect_not_configured(authed_client: TestClient) -> None:
    with patch(
        "apps.gateway.google_integrations_routes.google_oauth_configured",
        return_value=False,
    ):
        res = authed_client.get("/api/integrations/google/connect", follow_redirects=False)
    assert res.status_code == 503


def test_google_connect_redirect_when_configured(authed_client: TestClient) -> None:
    with (
        patch(
            "apps.gateway.google_integrations_routes.google_oauth_configured",
            return_value=True,
        ),
        patch(
            "apps.gateway.google_integrations_routes.create_pkce_state",
            return_value=("https://accounts.google.com/o/oauth2/auth?test=1", "state", "verifier"),
        ),
    ):
        res = authed_client.get(
            "/api/integrations/google/connect?permissions=mailbox_read,calendar_read",
            follow_redirects=False,
        )
    assert res.status_code == 307
    assert "accounts.google.com" in res.headers["location"]


def test_token_store_roundtrip(tmp_path) -> None:
    from services.integrations.google.token_store import (  # noqa: PLC0415
        delete_tokens,
        read_tokens,
        write_tokens,
    )

    op_id = uuid.uuid4()
    with patch("services.integrations.google.token_store.MAYA_GOOGLE_TOKEN_DIR", str(tmp_path)):
        write_tokens(op_id, {"refresh_token": "rt-test", "email": "a@example.com"})
        data = read_tokens(op_id)
        assert data is not None
        assert data["refresh_token"] == "rt-test"
        delete_tokens(op_id)
        assert read_tokens(op_id) is None
