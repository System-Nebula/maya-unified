"""Tests for cmd_registry core behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from services.cmd.bootstrap import ensure_cmds_registered
from services.cmd.dispatcher import dispatch_cmd_async
from services.cmd.models import CmdContext, CmdDefinition, CmdParameter, CmdResult, CmdSurface
from services.cmd.parser import parse_cmd_input, validate_args
from services.cmd.registry import registry


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch):
    from services.cmd import bootstrap

    monkeypatch.setattr(bootstrap, "_bootstrapped", False)
    registry._by_id.clear()
    registry._alias_index.clear()
    ensure_cmds_registered()


@pytest.fixture
def imagine_preflight_ok():
    """Stub the settings/health preflight so dispatch tests stay unit-level."""
    with (
        patch(
            "services.settings.store.load_effective_settings",
            return_value={"imagine": {"enabled": True, "comfyui_url": "http://127.0.0.1:3030"}},
        ),
        patch(
            "services.imagine.health.get_cached_comfyui_health",
            return_value={
                "status": "ok",
                "url": "http://127.0.0.1:3030",
                "weights": {
                    "ok": True,
                    "zit": {"ok": True, "missing": [], "detail": "ok"},
                    "krea2": {"ok": True, "missing": [], "detail": "ok", "capability": {"ok": True}},
                },
            },
        ),
        patch(
            "services.imagine.health.apply_comfyui_url_from_settings",
            return_value="http://127.0.0.1:3030",
        ),
    ):
        yield


def test_discovery_excludes_executor():
    help_cmd = registry.get("help")
    assert help_cmd is not None
    payload = help_cmd.discovery_dict()
    assert "executor" not in payload
    assert payload["id"] == "help"
    assert "chat" in payload["surfaces"]


def test_alias_resolution():
    parsed = parse_cmd_input("/img cyberpunk alley")
    assert parsed is not None
    assert parsed.cmd_id == "imagine"
    assert parsed.args["prompt"] == "cyberpunk alley"


def test_validate_missing_required_parameter():
    cmd = registry.get("imagine")
    assert cmd is not None
    assert validate_args(cmd, {}) == "missing required parameter: prompt"


def test_registry_discovery_by_surface():
    dashboard_cmds = registry.discovery(surface=CmdSurface.DASHBOARD)
    ids = {item["id"] for item in dashboard_cmds}
    assert {"help", "status", "imagine", "blend"}.issubset(ids)


@pytest.mark.asyncio
async def test_dispatch_help():
    parsed = parse_cmd_input("/help")
    assert parsed is not None
    result = await dispatch_cmd_async(
        parsed,
        CmdContext(surface=CmdSurface.CHAT),
    )
    assert result.ok is True
    assert "Available cmds" in result.text


@pytest.mark.asyncio
async def test_dispatch_imagine_async(imagine_preflight_ok):
    parsed = parse_cmd_input("/imagine neon alley")
    assert parsed is not None
    mock_result = {
        "job_id": "job-123",
        "status": "completed",
        "output_url": "https://example.com/out.png",
        "workflow_id": "a0000001-0000-4000-8000-000000000004",
        "provider_key": "comfyui:graph",
    }
    mock_run = AsyncMock(return_value=mock_result)
    with patch("services.cmd.executors.imagine.run_imagine_job", mock_run):
        result = await dispatch_cmd_async(
            parsed,
            CmdContext(surface=CmdSurface.DASHBOARD, operator_id="op-1"),
        )
    assert mock_run.call_args.kwargs["model"] == "zit"
    assert result.ok is True
    assert result.artifacts[0]["url"] == "https://example.com/out.png"
    assert result.artifacts[0]["job_id"] == "job-123"
    assert result.text == "Image ready."
    assert "job-123" not in result.text


@pytest.mark.asyncio
async def test_dispatch_imagine_defaults_zit_on_dashboard(imagine_preflight_ok):
    parsed = parse_cmd_input("/imagine a doge shiba inu anime style")
    assert parsed is not None
    mock_run = AsyncMock(
        return_value={
            "job_id": "job-doge",
            "status": "completed",
            "output_url": "https://example.com/doge.png",
            "workflow_id": "a0000001-0000-4000-8000-000000000004",
            "provider_key": "comfyui:graph",
        }
    )
    with patch("services.cmd.executors.imagine.run_imagine_job", mock_run):
        await dispatch_cmd_async(
            parsed,
            CmdContext(surface=CmdSurface.DASHBOARD, operator_id="op-1"),
        )
    assert mock_run.call_args.kwargs["model"] == "zit"
    assert mock_run.call_args.kwargs["prompt"] == "a doge shiba inu anime style"


@pytest.mark.asyncio
async def test_dispatch_imagine_uses_settings_default_model(imagine_preflight_ok):
    parsed = parse_cmd_input("/imagine a cat")
    assert parsed is not None
    settings = {
        "imagine": {
            "enabled": True,
            "comfyui_url": "http://127.0.0.1:3030",
            "default_model": "krea2",
        }
    }
    mock_run = AsyncMock(
        return_value={
            "job_id": "job-cat",
            "status": "completed",
            "output_url": "https://example.com/cat.png",
            "workflow_id": "a0000001-0000-4000-8000-000000000005",
            "provider_key": "comfyui:graph",
        }
    )
    with (
        patch("services.settings.store.load_effective_settings", return_value=settings),
        patch("services.cmd.executors.imagine.run_imagine_job", mock_run),
    ):
        await dispatch_cmd_async(
            parsed,
            CmdContext(surface=CmdSurface.DASHBOARD, operator_id="op-1"),
        )
    assert mock_run.call_args.kwargs["model"] == "krea2"


def test_parse_imagine_splits_inline_model_arg() -> None:
    parsed = parse_cmd_input("/imagine sunset model=krea2")
    assert parsed is not None
    assert parsed.args["prompt"] == "sunset"
    assert parsed.args["model"] == "krea2"


def test_parse_imagine_splits_multiple_inline_args() -> None:
    parsed = parse_cmd_input('/imagine sunset over mountains model=krea2 size=512x512')
    assert parsed is not None
    assert parsed.args["prompt"] == "sunset over mountains"
    assert parsed.args["model"] == "krea2"
    assert parsed.args["size"] == "512x512"


def test_parse_imagine_explicit_prompt_kwarg() -> None:
    parsed = parse_cmd_input("/imagine prompt=sunset model=krea2")
    assert parsed is not None
    assert parsed.args["prompt"] == "sunset"
    assert parsed.args["model"] == "krea2"


def test_cmd_result_to_chat_response_includes_correlation_fields() -> None:
    payload = CmdResult(
        ok=False,
        error="failed",
        trace_id="trace-abc",
        job_id="job-42",
        corr_id="c_test",
    ).to_chat_response()
    assert payload["ok"] is False
    assert payload["error"] == "failed"
    assert payload["trace_id"] == "trace-abc"
    assert payload["job_id"] == "job-42"
    assert payload["corr_id"] == "c_test"


@pytest.mark.asyncio
async def test_dispatch_imagine_failure_includes_trace_and_job_ids(imagine_preflight_ok):
    parsed = parse_cmd_input("/imagine neon alley")
    assert parsed is not None
    mock_run = AsyncMock(
        return_value={
            "job_id": "job-fail",
            "status": "failed",
            "output_url": "",
            "workflow_id": "wf-1",
            "provider_key": "comfyui:graph",
        }
    )
    with (
        patch("services.cmd.executors.imagine.run_imagine_job", mock_run),
        patch("services.cmd.executors.imagine._trace_id", return_value="trace-imagine"),
    ):
        result = await dispatch_cmd_async(
            parsed,
            CmdContext(surface=CmdSurface.DASHBOARD, operator_id="op-1"),
        )
    assert result.ok is False
    assert result.trace_id == "trace-imagine"
    assert result.job_id == "job-fail"


@pytest.mark.asyncio
async def test_dispatch_failure_backfills_trace_id():
    def _fail(_ctx, _args):
        return CmdResult(ok=False, error="boom")

    registry.register(
        CmdDefinition(
            id="failcmd",
            name="failcmd",
            description="Always fails",
            category="Utilities",
            surfaces=[CmdSurface.CHAT],
            executor=_fail,
        )
    )
    parsed = parse_cmd_input("/failcmd")
    assert parsed is not None
    with patch("services.cmd.dispatcher._cmd_trace_id", return_value="trace-dispatch"):
        result = await dispatch_cmd_async(parsed, CmdContext(surface=CmdSurface.CHAT))
    assert result.ok is False
    assert result.trace_id == "trace-dispatch"


def test_unknown_slash_is_not_parsed():
    assert parse_cmd_input("/not-a-real-cmd") is None


def test_custom_cmd_registration():
    def _echo(_ctx, args):
        return CmdResult(ok=True, text=str(args.get("text", "")))

    registry.register(
        CmdDefinition(
            id="echo",
            name="echo",
            description="Echo text",
            category="Utilities",
            parameters=[CmdParameter(name="text", type="string", required=True)],
            surfaces=[CmdSurface.CHAT],
            executor=_echo,
        )
    )
    parsed = parse_cmd_input("/echo hello world")
    assert parsed is not None
    assert parsed.args["text"] == "hello world"
