"""Tests for operator conversation clear route."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

sys.modules.setdefault("server", MagicMock(Hub=object))

from apps.gateway.voice_routes import register_agent_routes  # noqa: E402


@pytest.fixture
def voice_client():
    app = FastAPI()

    @app.middleware("http")
    async def _fake_operator(request, call_next):
        request.state.operator = MagicMock(id="op-test-1")
        return await call_next(request)

    register_agent_routes(app)
    return TestClient(app)


def test_conversation_clear_deletes_operator_history(voice_client: TestClient) -> None:
    with patch("services.operator_voice.context.clear_conversation", return_value=3) as mock_clear:
        res = voice_client.post("/api/voice/agent/conversation/clear")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["deleted_messages"] == 3
    mock_clear.assert_called_once_with("op-test-1")
