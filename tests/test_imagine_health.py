"""Tests for ComfyUI / imagine health probes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from services.imagine.health import (
    check_comfyui_health,
    format_comfyui_unavailable_error,
    get_cached_comfyui_health,
    invalidate_comfyui_health_cache,
    resolve_comfyui_url,
)


def test_resolve_comfyui_url_prefers_env(monkeypatch) -> None:
    monkeypatch.setenv("COMFYUI_API_URL", "http://env:3030")
    assert resolve_comfyui_url({"discord": {"comfyui_url": "http://settings:3000"}}) == "http://env:3030"


def test_resolve_comfyui_url_from_imagine_settings(monkeypatch) -> None:
    monkeypatch.delenv("COMFYUI_API_URL", raising=False)
    assert resolve_comfyui_url({"imagine": {"comfyui_url": "http://settings:3030/"}}) == "http://settings:3030"


def test_resolve_comfyui_url_from_settings(monkeypatch) -> None:
    monkeypatch.delenv("COMFYUI_API_URL", raising=False)
    assert resolve_comfyui_url({"discord": {"comfyui_url": "http://settings:3000/"}}) == "http://settings:3000"


def test_check_comfyui_health_html_404() -> None:
    resp = MagicMock()
    resp.status_code = 404
    resp.text = '<!DOCTYPE html><html><head><link href="/_next/static/css/app.css" />'

    with patch("services.discovery.comfyui.httpx.Client") as mock_client:
        client = MagicMock()
        client.__enter__.return_value = client
        client.get.return_value = resp
        mock_client.return_value = client
        result = check_comfyui_health("http://localhost:3000")

    assert result["status"] == "error"
    assert "HTML" in result["detail"] or "HTTP 404" in result["detail"]
    assert result["url"] == "http://localhost:3000"


def test_check_comfyui_health_ok_with_ready() -> None:
    ready = MagicMock()
    ready.status_code = 200

    with (
        patch("services.discovery.comfyui.httpx.Client") as mock_client,
        patch(
            "services.discovery.comfyui.probe_zimage_weights",
            return_value={"ok": True, "missing": [], "detail": "weights visible"},
        ),
    ):
        client = MagicMock()
        client.__enter__.return_value = client
        client.get.return_value = ready
        mock_client.return_value = client
        result = check_comfyui_health("http://127.0.0.1:3030")

    assert result["status"] == "ok"
    assert result["latency_ms"] is not None
    assert result["weights"]["ok"] is True


def test_check_comfyui_health_warns_when_weights_missing() -> None:
    ready = MagicMock()
    ready.status_code = 200

    with (
        patch("services.discovery.comfyui.httpx.Client") as mock_client,
        patch(
            "services.discovery.comfyui.probe_zimage_weights",
            return_value={
                "ok": False,
                "missing": ["z_image_turbo_bf16.safetensors"],
                "detail": "weights not visible",
            },
        ),
    ):
        client = MagicMock()
        client.__enter__.return_value = client
        client.get.return_value = ready
        mock_client.return_value = client
        result = check_comfyui_health("http://127.0.0.1:3030")

    assert result["status"] == "warn"
    assert result["weights"]["ok"] is False


def test_check_comfyui_health_connect_error() -> None:
    with patch("services.discovery.comfyui.httpx.Client") as mock_client:
        client = MagicMock()
        client.__enter__.return_value = client
        client.get.side_effect = httpx.ConnectError("connection refused")
        mock_client.return_value = client
        result = check_comfyui_health("http://127.0.0.1:3000")

    assert result["status"] == "error"
    assert "Cannot connect" in result["detail"]


def test_get_cached_comfyui_health_caches_ok(monkeypatch) -> None:
    invalidate_comfyui_health_cache()
    monkeypatch.delenv("COMFYUI_API_URL", raising=False)
    settings = {"discord": {"comfyui_url": "http://cache-test:3030"}}

    with patch(
        "services.discovery.comfyui.discover_comfyui_local",
        return_value={
            "id": "comfyui",
            "status": "ok",
            "detail": "ok",
            "url": "http://cache-test:3030",
            "latency_ms": 12,
        },
    ) as mock_check:
        first = get_cached_comfyui_health(settings, run_probe=True)
        second = get_cached_comfyui_health(settings, run_probe=True)

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert mock_check.call_count == 1


def test_get_cached_comfyui_health_run_probe_false_uses_cache(monkeypatch) -> None:
    invalidate_comfyui_health_cache()
    monkeypatch.delenv("COMFYUI_API_URL", raising=False)
    settings = {"imagine": {"comfyui_url": "http://cache-test:3030"}}
    cached_health = {
        "id": "comfyui",
        "status": "ok",
        "detail": "comfyui-api reachable",
        "url": "http://cache-test:3030",
        "latency_ms": 8,
    }

    with patch(
        "services.discovery.comfyui.discover_comfyui_local",
        return_value=cached_health,
    ) as mock_discover:
        get_cached_comfyui_health(settings, run_probe=True)
        result = get_cached_comfyui_health(settings, run_probe=False)

    assert result["status"] == "ok"
    assert result["detail"] == "comfyui-api reachable"
    assert mock_discover.call_count == 1


def test_get_cached_comfyui_health_run_probe_false_registry_fallback(monkeypatch) -> None:
    invalidate_comfyui_health_cache()
    monkeypatch.delenv("COMFYUI_API_URL", raising=False)
    settings = {"imagine": {"comfyui_url": "http://registry-test:3030"}}
    registry_health = {
        "id": "comfyui",
        "status": "ok",
        "detail": "startup probe ok",
        "url": "http://registry-test:3030",
        "latency_ms": 15,
    }

    with (
        patch("services.discovery.registry.get", return_value=registry_health),
        patch("services.discovery.comfyui.discover_comfyui_local") as mock_discover,
        patch("services.discovery.comfyui.probe_comfyui_url") as mock_probe,
    ):
        result = get_cached_comfyui_health(settings, run_probe=False)

    assert result["status"] == "ok"
    assert result["detail"] == "startup probe ok"
    mock_discover.assert_not_called()
    mock_probe.assert_not_called()


def test_get_cached_comfyui_health_run_probe_false_skipped_when_no_data(monkeypatch) -> None:
    invalidate_comfyui_health_cache()
    monkeypatch.delenv("COMFYUI_API_URL", raising=False)
    settings = {"imagine": {"comfyui_url": "http://empty-test:3030"}}

    with (
        patch("services.discovery.registry.get", return_value=None),
        patch("services.discovery.comfyui.discover_comfyui_local") as mock_discover,
    ):
        result = get_cached_comfyui_health(settings, run_probe=False)

    assert result["status"] == "skipped"
    assert result["detail"] == "Probe skipped"
    mock_discover.assert_not_called()


def test_format_comfyui_unavailable_error() -> None:
    msg = format_comfyui_unavailable_error(
        {"url": "http://localhost:3000", "detail": "Cannot connect"}
    )
    assert "ComfyUI is not reachable" in msg
    assert "localhost:3000" in msg
    assert "README.md" in msg
