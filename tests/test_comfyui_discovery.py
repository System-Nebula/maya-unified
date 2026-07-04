"""Tests for ComfyUI service discovery and auto-adopt."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import httpx

from services.discovery.comfyui import discover_comfyui_local, discovery_candidate_ports


def _docs_response(status: int, body: str) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = body
    return resp


def test_discovery_adopts_alternate_port(monkeypatch) -> None:
    monkeypatch.delenv("COMFYUI_API_URL", raising=False)
    monkeypatch.setenv("MAYA_COMFY_DISCOVERY_PORTS", "3000,3030")
    settings = {"imagine": {"comfyui_url": "http://127.0.0.1:3000"}}

    bad = _docs_response(404, '<!DOCTYPE html><html><head><link href="/_next/static/css/app.css" />')
    good = _docs_response(200, '{"openapi":"3.0.0"}')
    ready = _docs_response(200, "ready")

    def fake_get(url, *args, **kwargs):
        if url.endswith(":3000/docs"):
            return bad
        if url.endswith(":3030/docs"):
            return good
        if url.endswith(":3030/ready"):
            return ready
        raise AssertionError(f"unexpected url {url}")

    with patch("services.discovery.comfyui.httpx.Client") as mock_client:
        client = MagicMock()
        client.__enter__.return_value = client
        client.get.side_effect = fake_get
        mock_client.return_value = client
        result = discover_comfyui_local(settings, run_probe=True, adopt=True)

    assert result["status"] in ("ok", "warn")
    assert result.get("adopted_url") == "http://127.0.0.1:3030"
    assert "http://127.0.0.1:3000" in result.get("candidates_tried", [])
    assert os.environ.get("COMFYUI_API_URL") == "http://127.0.0.1:3030"


def test_discovery_no_candidates_returns_error(monkeypatch) -> None:
    monkeypatch.delenv("COMFYUI_API_URL", raising=False)
    monkeypatch.setenv("MAYA_COMFY_DISCOVERY_PORTS", "3030")
    settings = {"imagine": {"comfyui_url": "http://127.0.0.1:3000"}}

    with patch("services.discovery.comfyui.httpx.Client") as mock_client:
        client = MagicMock()
        client.__enter__.return_value = client
        client.get.side_effect = httpx.ConnectError("refused")
        mock_client.return_value = client
        result = discover_comfyui_local(settings, run_probe=True, adopt=False)

    assert result["status"] == "error"
    assert result.get("configured_url") == "http://127.0.0.1:3000"


def test_discovery_candidate_ports_env_override(monkeypatch) -> None:
    monkeypatch.setenv("MAYA_COMFY_DISCOVERY_PORTS", "4000, 5000")
    assert discovery_candidate_ports() == [4000, 5000]
