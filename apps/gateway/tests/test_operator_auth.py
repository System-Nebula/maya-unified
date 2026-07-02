"""Operator auth tests for the Maya Unified gateway."""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.paths import setup_paths

setup_paths()

from apps.gateway.auth_routes import router as auth_router  # noqa: E402
from services.auth.operator_store import get_db_session, hash_password  # noqa: E402
from services.auth.session import OPERATOR_SESSION_COOKIE  # noqa: E402


@dataclass
class FakeOperator:
    id: uuid.UUID
    username: str
    display_name: str
    password_hash: str
    role: str = "operator"
    avatar_color: str = "#0a84ff"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_login: datetime | None = None


class FakeStore:
    def __init__(self) -> None:
        self.ops: dict[uuid.UUID, FakeOperator] = {}

    async def any_operators_exist(self, _session) -> bool:
        return bool(self.ops)

    async def count_admins(self, _session) -> int:
        return sum(1 for o in self.ops.values() if o.role == "admin")

    async def get_by_username(self, _session, username: str) -> FakeOperator | None:
        for op in self.ops.values():
            if op.username == username.strip().lower():
                return op
        return None

    async def get_by_id(self, _session, operator_id) -> FakeOperator | None:
        oid = uuid.UUID(str(operator_id))
        return self.ops.get(oid)

    async def list_operators(self, _session) -> list[FakeOperator]:
        return sorted(self.ops.values(), key=lambda o: o.created_at)

    async def create_operator(
        self,
        _session,
        *,
        username: str,
        display_name: str,
        password: str,
        role: str = "operator",
        avatar_color: str | None = None,
        skip_password_validation: bool = False,
    ) -> FakeOperator:
        from services.auth.operator_store import validate_password, validate_role

        if not skip_password_validation:
            validate_password(password)
        validate_role(role)
        oid = uuid.uuid4()
        op = FakeOperator(
            id=oid,
            username=username.strip().lower(),
            display_name=display_name.strip(),
            password_hash=hash_password(password),
            role=role,
            avatar_color=avatar_color or "#0a84ff",
        )
        self.ops[oid] = op
        return op

    async def update_operator(
        self,
        _session,
        operator_id,
        *,
        display_name=None,
        role=None,
        avatar_color=None,
        password=None,
    ) -> FakeOperator:
        from services.auth.operator_store import validate_password, validate_role

        op = await self.get_by_id(_session, operator_id)
        if op is None:
            raise ValueError(f"operator {operator_id} not found")
        if role is not None:
            validate_role(role)
            if op.role == "admin" and role != "admin" and await self.count_admins(_session) <= 1:
                raise ValueError("cannot demote last admin")
            op.role = role
        if display_name is not None:
            op.display_name = display_name.strip()
        if avatar_color is not None:
            op.avatar_color = avatar_color
        if password is not None:
            validate_password(password)
            op.password_hash = hash_password(password)
        return op

    async def delete_operator(self, _session, operator_id) -> None:
        op = await self.get_by_id(_session, operator_id)
        if op is None:
            raise ValueError(f"operator {operator_id} not found")
        if op.role == "admin" and await self.count_admins(_session) <= 1:
            raise ValueError("cannot delete last admin")
        del self.ops[op.id]

    async def touch_last_login(self, _session, operator_id) -> None:
        op = await self.get_by_id(_session, operator_id)
        if op is not None:
            op.last_login = datetime.now(timezone.utc)


@pytest.fixture
def fake_store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def auth_app(fake_store: FakeStore, monkeypatch) -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router)

    async def fake_session() -> AsyncGenerator[object, None]:
        yield object()

    app.dependency_overrides[get_db_session] = fake_session

    import apps.gateway.auth_routes as routes_mod

    monkeypatch.setattr(routes_mod, "any_operators_exist", fake_store.any_operators_exist)
    monkeypatch.setattr(routes_mod, "get_by_username", fake_store.get_by_username)
    monkeypatch.setattr(routes_mod, "get_by_id", fake_store.get_by_id)
    monkeypatch.setattr(routes_mod, "list_operators", fake_store.list_operators)
    monkeypatch.setattr(routes_mod, "create_operator", fake_store.create_operator)
    monkeypatch.setattr(routes_mod, "update_operator", fake_store.update_operator)
    monkeypatch.setattr(routes_mod, "delete_operator", fake_store.delete_operator)
    monkeypatch.setattr(routes_mod, "touch_last_login", fake_store.touch_last_login)

    import services.auth.deps as deps_mod

    monkeypatch.setattr(deps_mod, "get_by_id", fake_store.get_by_id)

    return app


@pytest.fixture
def client(auth_app: FastAPI) -> TestClient:
    return TestClient(auth_app)


def _login(client: TestClient, username: str, password: str) -> None:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200


def test_me_setup_required_when_empty(client: TestClient) -> None:
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["setup_required"] is True


def test_first_run_create_admin_without_cookie(client: TestClient) -> None:
    r = client.post(
        "/api/operators",
        json={"username": "admin", "display_name": "Admin", "password": "password123"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["operator"]["role"] == "admin"
    assert body["operator"]["username"] == "admin"


def test_login_and_me(client: TestClient) -> None:
    client.post(
        "/api/operators",
        json={"username": "admin", "display_name": "Admin", "password": "password123"},
    )
    _login(client, "admin", "password123")
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["authenticated"] is True
    assert body["username"] == "admin"
    assert body["role"] == "admin"
    assert "avatar_color" in body


def test_list_operators_requires_admin(client: TestClient, fake_store: FakeStore) -> None:
    import asyncio

    async def setup() -> None:
        await fake_store.create_operator(
            object(), username="admin", display_name="Admin", password="password123", role="admin"
        )
        await fake_store.create_operator(
            object(), username="op1", display_name="Op", password="password123", role="operator"
        )

    asyncio.run(setup())

    r = client.get("/api/operators")
    assert r.status_code == 401

    _login(client, "op1", "password123")
    r = client.get("/api/operators")
    assert r.status_code == 403

    _login(client, "admin", "password123")
    r = client.get("/api/operators")
    assert r.status_code == 200
    assert len(r.json()["operators"]) == 2


def test_cannot_delete_self(client: TestClient, fake_store: FakeStore) -> None:
    import asyncio

    async def setup() -> FakeOperator:
        return await fake_store.create_operator(
            object(), username="admin", display_name="Admin", password="password123", role="admin"
        )

    admin = asyncio.run(setup())
    _login(client, "admin", "password123")
    r = client.delete(f"/api/operators/{admin.id}")
    assert r.status_code == 400
    assert "own account" in r.json()["detail"]


def test_cannot_delete_last_admin(client: TestClient, fake_store: FakeStore) -> None:
    client.post(
        "/api/operators",
        json={"username": "admin", "display_name": "Admin", "password": "password123"},
    )
    _login(client, "admin", "password123")
    r = client.post(
        "/api/operators",
        json={"username": "admin2", "display_name": "Admin 2", "password": "password123", "role": "admin"},
    )
    assert r.status_code == 200
    admin2_id = r.json()["operator"]["id"]
    _login(client, "admin2", "password123")
    # Remove first admin while two exist
    admin1 = next(o for o in fake_store.ops.values() if o.username == "admin")
    r = client.delete(f"/api/operators/{admin1.id}")
    assert r.status_code == 200
    # Now admin2 is the sole admin — cannot demote
    r = client.patch(f"/api/operators/{admin2_id}", json={"role": "operator"})
    assert r.status_code == 400
    assert "last admin" in r.json()["detail"]


def test_cannot_demote_last_admin(client: TestClient, fake_store: FakeStore) -> None:
    client.post(
        "/api/operators",
        json={"username": "admin", "display_name": "Admin", "password": "password123"},
    )
    _login(client, "admin", "password123")
    admin = next(o for o in fake_store.ops.values() if o.username == "admin")
    r = client.patch(f"/api/operators/{admin.id}", json={"role": "operator"})
    assert r.status_code == 400
    assert "last admin" in r.json()["detail"]


def test_store_rejects_delete_last_admin(fake_store: FakeStore) -> None:
    import asyncio

    async def run() -> None:
        admin = await fake_store.create_operator(
            object(), username="admin", display_name="Admin", password="password123", role="admin"
        )
        with pytest.raises(ValueError, match="last admin"):
            await fake_store.delete_operator(object(), admin.id)

    asyncio.run(run())


def test_short_password_rejected(client: TestClient) -> None:
    r = client.post(
        "/api/operators",
        json={"username": "admin", "display_name": "Admin", "password": "short"},
    )
    assert r.status_code == 400
    assert "8 characters" in r.json()["detail"]


def test_operator_me_response_shape_not_platform(client: TestClient) -> None:
    """Operator /api/auth/me returns dashboard shape, not platform MeResponse."""
    client.post(
        "/api/operators",
        json={"username": "admin", "display_name": "Admin", "password": "password123"},
    )
    _login(client, "admin", "password123")
    r = client.get("/api/auth/me")
    body = r.json()
    assert "authenticated" in body
    assert "auth_enabled" not in body
    assert "setup_required" not in body or body.get("authenticated")


def test_protected_voice_api_returns_401_without_session() -> None:
    """Middleware on main app blocks unauthenticated voice API access."""
    with patch("apps.gateway.main.register_agent_routes"):
        with patch("apps.gateway.main._mount_platform_routes"):
            from apps.gateway.main import app as main_app

            with patch(
                "apps.gateway.main.any_operators_exist",
                new=AsyncMock(return_value=True),
            ):
                client = TestClient(main_app)
                r = client.get("/api/voice/agent/status")
                assert r.status_code == 401
                assert r.json()["detail"] == "not authenticated"


def test_seed_default_operator_if_needed_creates_admin(fake_store: FakeStore, monkeypatch) -> None:
    import asyncio

    import services.auth.seed as seed_mod

    monkeypatch.setattr(seed_mod, "any_operators_exist", fake_store.any_operators_exist)
    monkeypatch.setattr(seed_mod, "create_operator", fake_store.create_operator)

    async def run() -> None:
        assert await seed_mod.seed_default_operator_if_needed(object()) is True
        assert await seed_mod.seed_default_operator_if_needed(object()) is False
        assert len(fake_store.ops) == 1
        op = next(iter(fake_store.ops.values()))
        assert op.username == "admin"
        assert op.role == "admin"

    asyncio.run(run())


def test_default_credentials_login(client: TestClient, fake_store: FakeStore) -> None:
    import asyncio

    async def seed() -> None:
        await fake_store.create_operator(
            object(),
            username="admin",
            display_name="Admin",
            password="admin",
            role="admin",
            skip_password_validation=True,
        )

    asyncio.run(seed())
    _login(client, "admin", "admin")
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["authenticated"] is True
    assert r.json()["username"] == "admin"


def test_seed_default_operator_allows_short_bootstrap_password(fake_store: FakeStore, monkeypatch) -> None:
    import asyncio

    import services.auth.seed as seed_mod

    monkeypatch.setattr(seed_mod, "any_operators_exist", fake_store.any_operators_exist)
    monkeypatch.setattr(seed_mod, "create_operator", fake_store.create_operator)

    async def run() -> None:
        assert await seed_mod.seed_default_operator_if_needed(object()) is True
        op = next(iter(fake_store.ops.values()))
        assert op.username == "admin"
        from services.auth.passwords import verify_password
        assert verify_password(op.password_hash, "admin")

    asyncio.run(run())
