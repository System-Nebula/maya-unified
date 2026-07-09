"""OTEL traceparent extraction and telemetry beacon route."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from apps.gateway.main import _otel_traceparent  # noqa: E402
from apps.gateway.telemetry_routes import router as telemetry_router  # noqa: E402


def _trace_app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(_otel_traceparent)
    app.include_router(telemetry_router)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    return app


def test_traceparent_middleware_attaches_extracted_context():
    fake_ctx = object()
    with patch("opentelemetry.propagate.extract", return_value=fake_ctx) as extract:
        with patch("opentelemetry.context.attach", return_value="token") as attach:
            with patch("opentelemetry.context.detach") as detach:
                client = TestClient(_trace_app())
                resp = client.get(
                    "/ping",
                    headers={"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"},
                )
    assert resp.status_code == 200
    extract.assert_called_once()
    attach.assert_called_once_with(fake_ctx)
    detach.assert_called_once_with("token")


def test_traceparent_middleware_skips_when_header_missing():
    with patch("opentelemetry.context.attach") as attach:
        client = TestClient(_trace_app())
        resp = client.get("/ping")
    assert resp.status_code == 200
    attach.assert_not_called()


def test_telemetry_event_endpoint_accepts_beacon():
    with patch("apps.gateway.telemetry_routes.corr_span") as corr_span:
        corr_span.return_value.__enter__ = MagicMock(return_value=MagicMock())
        corr_span.return_value.__exit__ = MagicMock(return_value=False)
        client = TestClient(_trace_app())
        resp = client.post(
            "/api/telemetry/event",
            headers={"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4737-00f067aa0ba902b8-01"},
            json={"event": "yt-ready", "corr_id": "c_test123", "attrs": {"setUseYt": True}},
        )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    corr_span.assert_called_once()
    args, kwargs = corr_span.call_args
    assert args[0] == "ui.player.yt-ready"
    assert kwargs.get("chat.corr_id") == "c_test123"
    assert kwargs.get("event") == "yt-ready"
