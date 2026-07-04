"""Tests for /imagine cmd executor preflight and error handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from services.cmd.executors.imagine import exec_imagine
from services.cmd.models import CmdContext, CmdSurface


@pytest.mark.asyncio
async def test_exec_imagine_blocked_when_disabled() -> None:
    ctx = CmdContext(operator_id="op-1", surface=CmdSurface.CHAT)
    settings = {"imagine": {"enabled": False, "comfyui_url": "http://127.0.0.1:3030"}}

    with patch("services.settings.store.load_effective_settings", return_value=settings):
        result = await exec_imagine(ctx, {"prompt": "a cat"})

    assert result.ok is False
    assert "disabled in Settings" in (result.error or "")
    assert "Imagine" in (result.error or "")


@pytest.mark.asyncio
async def test_exec_imagine_blocked_when_disabled_legacy_discord() -> None:
    ctx = CmdContext(operator_id="op-1", surface=CmdSurface.CHAT)
    settings = {"discord": {"imagine_enabled": False, "comfyui_url": "http://127.0.0.1:3030"}}

    with patch("services.settings.store.load_effective_settings", return_value=settings):
        result = await exec_imagine(ctx, {"prompt": "a cat"})

    assert result.ok is False
    assert "disabled in Settings" in (result.error or "")


@pytest.mark.asyncio
async def test_exec_imagine_dev_policy_blocks(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "development")
    monkeypatch.delenv("MAYA_FAKE_COMFY", raising=False)
    ctx = CmdContext(operator_id="op-1", surface=CmdSurface.CHAT)
    settings = {"imagine": {"enabled": True, "comfyui_url": "http://127.0.0.1:3030"}}
    health = {"status": "error", "detail": "down", "url": "http://127.0.0.1:3030"}

    with (
        patch("services.settings.store.load_effective_settings", return_value=settings),
        patch("services.imagine.health.apply_comfyui_url_from_settings", return_value="http://127.0.0.1:3030"),
        patch("services.imagine.health.get_cached_comfyui_health", return_value=health),
        patch("services.cmd.executors.imagine.run_imagine_job", new_callable=AsyncMock) as mock_run,
    ):
        result = await exec_imagine(ctx, {"prompt": "a cat"})

    assert result.ok is False
    assert "Dev policy requires" in (result.error or "")
    mock_run.assert_not_called()


@pytest.mark.asyncio
async def test_exec_imagine_preflight_blocks_unreachable_comfyui(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("MAYA_FAKE_COMFY", raising=False)
    ctx = CmdContext(operator_id="op-1", surface=CmdSurface.CHAT)
    settings = {"imagine": {"enabled": True, "comfyui_url": "http://127.0.0.1:3030"}}
    health = {
        "status": "error",
        "detail": "Cannot connect",
        "url": "http://127.0.0.1:3030",
        "latency_ms": 5,
    }

    with (
        patch("services.settings.store.load_effective_settings", return_value=settings),
        patch("services.imagine.health.apply_comfyui_url_from_settings", return_value="http://127.0.0.1:3030"),
        patch("services.imagine.health.get_cached_comfyui_health", return_value=health),
        patch("services.cmd.executors.imagine.run_imagine_job", new_callable=AsyncMock) as mock_run,
    ):
        result = await exec_imagine(ctx, {"prompt": "a cat"})

    assert result.ok is False
    assert "ComfyUI is not reachable" in (result.error or "")
    mock_run.assert_not_called()


@pytest.mark.asyncio
async def test_exec_imagine_preflight_blocks_missing_weights() -> None:
    ctx = CmdContext(operator_id="op-1", surface=CmdSurface.CHAT)
    settings = {"imagine": {"enabled": True, "comfyui_url": "http://127.0.0.1:3030", "default_model": "zit"}}
    health = {
        "status": "ok",
        "detail": "ok",
        "url": "http://127.0.0.1:3030",
        "latency_ms": 5,
        "weights": {
            "ok": False,
            "zit": {
                "ok": False,
                "missing": ["z_image_turbo_bf16.safetensors"],
                "detail": "Z-Image weights not visible to ComfyUI",
            },
            "krea2": {"ok": True, "missing": [], "detail": "Krea 2 Turbo weights visible to ComfyUI"},
        },
    }

    with (
        patch("services.settings.store.load_effective_settings", return_value=settings),
        patch("services.imagine.health.apply_comfyui_url_from_settings", return_value="http://127.0.0.1:3030"),
        patch("services.imagine.health.get_cached_comfyui_health", return_value=health),
        patch("services.cmd.executors.imagine.run_imagine_job", new_callable=AsyncMock) as mock_run,
    ):
        result = await exec_imagine(ctx, {"prompt": "a cat"})

    assert result.ok is False
    assert "Z-Image Turbo weights missing" in (result.error or "")
    assert "z_image_turbo_bf16.safetensors" in (result.error or "")
    assert "infra/comfyui/README.md" in (result.error or "")
    mock_run.assert_not_called()


@pytest.mark.asyncio
async def test_exec_imagine_preflight_blocks_missing_krea2_weights_only() -> None:
    ctx = CmdContext(operator_id="op-1", surface=CmdSurface.CHAT)
    settings = {"imagine": {"enabled": True, "comfyui_url": "http://127.0.0.1:3030", "default_model": "zit"}}
    health = {
        "status": "ok",
        "detail": "ok",
        "url": "http://127.0.0.1:3030",
        "latency_ms": 5,
        "weights": {
            "ok": False,
            "zit": {"ok": True, "missing": [], "detail": "Z-Image Turbo weights visible to ComfyUI"},
            "krea2": {
                "ok": False,
                "missing": ["krea2_turbo_fp8_scaled.safetensors"],
                "detail": "Krea 2 Turbo weights not visible to ComfyUI",
            },
        },
    }

    with (
        patch("services.settings.store.load_effective_settings", return_value=settings),
        patch("services.imagine.health.apply_comfyui_url_from_settings", return_value="http://127.0.0.1:3030"),
        patch("services.imagine.health.get_cached_comfyui_health", return_value=health),
        patch("services.cmd.executors.imagine.run_imagine_job", new_callable=AsyncMock) as mock_run,
    ):
        result = await exec_imagine(ctx, {"prompt": "a cat", "model": "krea2"})

    assert result.ok is False
    assert "Krea 2 Turbo weights missing" in (result.error or "")
    assert "krea2_turbo_fp8_scaled.safetensors" in (result.error or "")
    mock_run.assert_not_called()


@pytest.mark.asyncio
async def test_exec_imagine_preflight_blocks_krea2_without_capability() -> None:
    ctx = CmdContext(operator_id="op-1", surface=CmdSurface.CHAT)
    settings = {"imagine": {"enabled": True, "comfyui_url": "http://127.0.0.1:3030", "default_model": "zit"}}
    health = {
        "status": "warn",
        "detail": "ok",
        "url": "http://127.0.0.1:3030",
        "latency_ms": 5,
        "weights": {
            "ok": False,
            "zit": {"ok": True, "missing": [], "detail": "Z-Image Turbo weights visible to ComfyUI"},
            "krea2": {
                "ok": False,
                "missing": [],
                "detail": "Krea 2 requires ComfyUI 0.26+",
                "capability": {
                    "ok": False,
                    "comfyui_version": "0.19.3",
                    "detail": (
                        "Krea 2 requires ComfyUI 0.26+ (CLIPLoader type `krea2`). "
                        "Your ComfyUI is 0.19.3. Rebuild comfyui-api — see infra/comfyui/README.md."
                    ),
                },
            },
        },
    }

    with (
        patch("services.settings.store.load_effective_settings", return_value=settings),
        patch("services.imagine.health.apply_comfyui_url_from_settings", return_value="http://127.0.0.1:3030"),
        patch("services.imagine.health.get_cached_comfyui_health", return_value=health),
        patch("services.cmd.executors.imagine.run_imagine_job", new_callable=AsyncMock) as mock_run,
    ):
        result = await exec_imagine(ctx, {"prompt": "sunset", "model": "krea2"})

    assert result.ok is False
    assert "0.26" in (result.error or "")
    assert "0.19.3" in (result.error or "")
    mock_run.assert_not_called()


@pytest.mark.asyncio
async def test_exec_imagine_allows_krea2_when_zit_missing() -> None:
    ctx = CmdContext(operator_id="op-1", surface=CmdSurface.CHAT)
    settings = {"imagine": {"enabled": True, "comfyui_url": "http://127.0.0.1:3030", "default_model": "zit"}}
    health = {
        "status": "warn",
        "detail": "ok",
        "url": "http://127.0.0.1:3030",
        "latency_ms": 5,
        "weights": {
            "ok": False,
            "zit": {
                "ok": False,
                "missing": ["z_image_turbo_bf16.safetensors"],
                "detail": "Z-Image weights not visible to ComfyUI",
            },
            "krea2": {
                "ok": True,
                "missing": [],
                "detail": "Krea 2 Turbo ready",
                "capability": {"ok": True, "comfyui_version": "0.26.0"},
            },
        },
    }

    with (
        patch("services.settings.store.load_effective_settings", return_value=settings),
        patch("services.imagine.health.apply_comfyui_url_from_settings", return_value="http://127.0.0.1:3030"),
        patch("services.imagine.health.get_cached_comfyui_health", return_value=health),
        patch(
            "services.cmd.executors.imagine.run_imagine_job",
            new_callable=AsyncMock,
            return_value={
                "job_id": "job-krea",
                "status": "completed",
                "output_url": "http://example.com/out.png",
                "error": None,
            },
        ) as mock_run,
    ):
        result = await exec_imagine(ctx, {"prompt": "a cat", "model": "krea2"})

    assert result.ok is True
    assert mock_run.call_args.kwargs["model"] == "krea2"


@pytest.mark.asyncio
async def test_exec_imagine_surfaces_job_error() -> None:
    ctx = CmdContext(operator_id="op-1", surface=CmdSurface.CHAT)
    settings = {"imagine": {"enabled": True, "comfyui_url": "http://127.0.0.1:3030"}}
    health = {"status": "ok", "detail": "ok", "url": "http://127.0.0.1:3030", "latency_ms": 5}

    with (
        patch("services.settings.store.load_effective_settings", return_value=settings),
        patch("services.imagine.health.apply_comfyui_url_from_settings", return_value="http://127.0.0.1:3030"),
        patch("services.imagine.health.get_cached_comfyui_health", return_value=health),
        patch(
            "services.cmd.executors.imagine.run_imagine_job",
            new_callable=AsyncMock,
            return_value={
                "job_id": "job-42",
                "status": "failed",
                "error": "sampler OOM",
                "output_url": "",
            },
        ),
    ):
        result = await exec_imagine(ctx, {"prompt": "a cat"})

    assert result.ok is False
    assert "job-42" in (result.error or "")
    assert "sampler OOM" in (result.error or "")


@pytest.mark.asyncio
async def test_exec_imagine_passes_corr_id_in_metadata() -> None:
    ctx = CmdContext(
        operator_id="op-1",
        surface=CmdSurface.DASHBOARD,
        metadata={"corr_id": "c_test_corr"},
    )
    settings = {"imagine": {"enabled": True, "comfyui_url": "http://127.0.0.1:3030"}}
    health = {"status": "ok", "detail": "ok", "url": "http://127.0.0.1:3030", "latency_ms": 5}

    with (
        patch("services.settings.store.load_effective_settings", return_value=settings),
        patch("services.imagine.health.apply_comfyui_url_from_settings", return_value="http://127.0.0.1:3030"),
        patch("services.imagine.health.get_cached_comfyui_health", return_value=health),
        patch(
            "services.cmd.executors.imagine.run_imagine_job",
            new_callable=AsyncMock,
            return_value={
                "job_id": "job-99",
                "status": "completed",
                "output_url": "http://example.com/out.png",
                "error": None,
            },
        ) as mock_run,
        patch("services.cmd.executors.imagine._trace_id", return_value="traceabc123"),
    ):
        result = await exec_imagine(ctx, {"prompt": "a cat"})

    assert result.ok is True
    assert result.trace_id == "traceabc123"
    assert result.job_id == "job-99"
    meta = mock_run.call_args.kwargs["metadata"]
    assert meta["corr_id"] == "c_test_corr"
    assert meta["surface"] == "dashboard"
