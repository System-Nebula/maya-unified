"""Tests for imagine_generate agent tool."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_VOICE_RUNTIME = Path(__file__).resolve().parents[1] / "packages" / "voice-runtime"
if str(_VOICE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_VOICE_RUNTIME))


@pytest.fixture
def imagine_settings_enabled():
    settings = {"imagine": {"enabled": True, "comfyui_url": "http://127.0.0.1:3030"}}
    with patch("services.settings.store.load_effective_settings", return_value=settings):
        yield


def test_imagine_generate_handler_requires_prompt(imagine_settings_enabled) -> None:
    from tools.imagine import _imagine_generate_handler

    with pytest.raises(ValueError, match="prompt"):
        _imagine_generate_handler({})


def test_imagine_generate_handler_returns_json(imagine_settings_enabled) -> None:
    from tools.imagine import _imagine_generate_handler

    mock_result = {
        "job_id": "job-1",
        "status": "completed",
        "output_url": "/imagine-outputs/out.png",
        "model_label": "Z-Image Turbo",
        "model_key": "z-image-turbo",
        "workflow_id": "wf-1",
        "workflow_name": "z-image-turbo-t2i",
        "gen_ms": 5000,
    }
    with patch("tools.imagine._run_imagine_sync", return_value=mock_result):
        out = _imagine_generate_handler({"prompt": "a cat", "model": "zit"})
    assert out["ok"] is True
    assert out["url"] == "/imagine-outputs/out.png"
    assert out["prompt"] == "a cat"


def test_imagine_generate_handler_uses_settings_default_when_model_omitted() -> None:
    from tools.imagine import _imagine_generate_handler

    settings = {
        "imagine": {
            "enabled": True,
            "comfyui_url": "http://127.0.0.1:3030",
            "default_model": "krea2",
        },
    }
    mock_result = {
        "job_id": "job-krea",
        "status": "completed",
        "output_url": "/imagine-outputs/dog.png",
        "model_label": "Krea 2 Turbo",
        "model_key": "krea2",
        "workflow_id": "wf-krea",
        "workflow_name": "krea2-turbo-t2i",
        "gen_ms": 45000,
    }
    with (
        patch("services.settings.store.load_effective_settings", return_value=settings),
        patch("tools.imagine._run_imagine_sync", return_value=mock_result) as mock_run,
    ):
        out = _imagine_generate_handler({"prompt": "a dog"})
    assert out["ok"] is True
    mock_run.assert_called_once()
    assert mock_run.call_args.kwargs["model"] == "krea2"


def test_tool_loop_finishes_imagine_remark() -> None:
    from llm import LLMResponse, ToolCall
    from tools.executor import ToolExecutor
    from tools.loop import ToolLoop
    from tools.registry import ToolRegistry, ToolSpec

    registry = ToolRegistry()

    def handler(_args: dict) -> dict:
        return {
            "ok": True,
            "url": "/imagine-outputs/x.png",
            "prompt": "sunset",
            "model": "Z-Image Turbo",
            "job_id": "j1",
        }

    registry.register(
        ToolSpec(
            name="imagine_generate",
            description="test",
            parameters={"type": "object", "properties": {}},
            handler=handler,
        )
    )
    executor = ToolExecutor(registry, timeout=5.0)

    class FakeLLM:
        def base_system_prompt(self, **kwargs):
            return "You are Maya."

        def complete(self, messages, tools=None, model=None, max_tokens=None):
            if tools:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="tc1",
                            name="imagine_generate",
                            arguments={"prompt": "sunset"},
                            raw_arguments="{}",
                        ),
                    ],
                )
            return LLMResponse(content="that sunset you'll never see")

        def stream_messages(self, messages, model=None):
            yield "that sunset you'll never see"

    loop = ToolLoop(FakeLLM(), registry, executor, max_rounds=2, mode="native")
    settings = {"imagine": {"remark_enabled": True}}
    with (
        patch("services.imagine.remark.remark_enabled", return_value=True),
        patch("services.settings.store.load_effective_settings", return_value=settings),
        patch("services.imagine.tool_context.get_imagine_tool_context", return_value={}),
    ):
        result = loop.run([{"role": "system", "content": "sys"}, {"role": "user", "content": "draw sunset"}])
    assert "sunset" in result.final_text.lower()


def test_trace_has_imagine_success() -> None:
    from services.imagine.chat_fallback import trace_has_imagine_success

    ok_trace = [
        {
            "tool": "imagine_generate",
            "result": '{"ok": true, "url": "/imagine-outputs/x.png", "prompt": "cat"}',
        }
    ]
    assert trace_has_imagine_success(ok_trace) is True
    assert trace_has_imagine_success([]) is False
    assert trace_has_imagine_success([{"tool": "imagine_generate", "result": '{"ok": false}'}]) is False


def test_run_imagine_nl_fallback_when_handler_succeeds(imagine_settings_enabled) -> None:
    from services.imagine.chat_fallback import run_imagine_nl_fallback

    mock_result = {
        "ok": True,
        "url": "/imagine-outputs/dog.png",
        "job_id": "j-dog",
        "model": "Z-Image Turbo",
        "model_key": "z-image-turbo",
        "prompt": "stupid dog wearing a party hat",
        "gen_ms": 9000,
    }
    emitted: list[dict] = []

    class FakeLLM:
        def base_system_prompt(self, **kwargs):
            return "You are Maya."

        def stream_messages(self, messages, model=None):
            yield "absolute menace of a dog"

    settings = {"imagine": {"enabled": True, "default_model": "krea2", "remark_enabled": True}}
    with (
        patch("tools.imagine._run_imagine_sync") as mock_run,
        patch("services.imagine.remark.remark_enabled", return_value=True),
        patch("services.settings.store.load_effective_settings", return_value=settings),
    ):
        mock_run.return_value = {
            "job_id": "j-dog",
            "status": "completed",
            "output_url": "/imagine-outputs/dog.png",
            "model_label": "Krea 2 Turbo",
            "model_key": "krea2",
            "gen_ms": 9000,
        }
        reply, streamed = run_imagine_nl_fallback(
            user_text="draw a stupid dog wearing a party hat",
            operator_id="op1",
            corr_id="c_test",
            messages=[{"role": "user", "content": "draw a stupid dog wearing a party hat"}],
            llm=FakeLLM(),
            emit=lambda **ev: emitted.append(ev),
            settings=settings,
        )
    assert mock_run.call_args.kwargs["model"] == "krea2"
    assert "menace" in reply.lower() or "dog" in reply.lower()
    assert streamed is True
    artifact_events = [e for e in emitted if e.get("artifacts")]
    assert artifact_events
    assert artifact_events[0]["artifacts"][0]["url"] == "/imagine-outputs/dog.png"


def test_tool_loop_returns_remark_not_job_id_after_imagine_success() -> None:
    from llm import LLMResponse, ToolCall
    from tools.executor import ToolExecutor
    from tools.loop import ToolLoop
    from tools.registry import ToolRegistry, ToolSpec

    job_id = "de5d48e0-6bbb-4b5c-8195-b895715ca0bb"

    registry = ToolRegistry()

    def handler(_args: dict) -> dict:
        return {
            "ok": True,
            "url": "/imagine-outputs/x.png",
            "prompt": "party dog",
            "model": "Krea 2 Turbo",
            "job_id": job_id,
        }

    registry.register(
        ToolSpec(
            name="imagine_generate",
            description="test",
            parameters={"type": "object", "properties": {}},
            handler=handler,
        )
    )
    executor = ToolExecutor(registry, timeout=5.0)

    class FakeLLM:
        call_count = 0

        def base_system_prompt(self, **kwargs):
            return "You are Maya."

        def complete(self, messages, tools=None, model=None, max_tokens=None):
            FakeLLM.call_count += 1
            if tools:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="tc1",
                            name="imagine_generate",
                            arguments={"prompt": "party dog"},
                            raw_arguments="{}",
                        ),
                    ],
                )
            return LLMResponse(content=job_id)

        def stream_messages(self, messages, model=None):
            yield "here is your ridiculous party dog"

    loop = ToolLoop(FakeLLM(), registry, executor, max_rounds=3, mode="native")
    settings = {"imagine": {"remark_enabled": True}}
    with (
        patch("services.imagine.remark.remark_enabled", return_value=True),
        patch("services.settings.store.load_effective_settings", return_value=settings),
        patch("services.imagine.tool_context.get_imagine_tool_context", return_value={}),
    ):
        result = loop.run(
            [{"role": "system", "content": "sys"}, {"role": "user", "content": "draw party dog"}],
        )
    assert "party dog" in result.final_text.lower()
    assert result.final_text.strip() != job_id
    assert FakeLLM.call_count == 1


def test_tool_loop_dedupes_parallel_imagine_generate() -> None:
    from llm import LLMResponse, ToolCall
    from tools.executor import ToolExecutor
    from tools.loop import ToolLoop
    from tools.registry import ToolRegistry, ToolSpec

    registry = ToolRegistry()
    calls: list[int] = []

    def handler(_args: dict) -> dict:
        calls.append(1)
        return {
            "ok": True,
            "url": "/imagine-outputs/x.png",
            "prompt": "party dog",
            "model": "Krea 2 Turbo",
            "job_id": "job-1",
        }

    registry.register(
        ToolSpec(
            name="imagine_generate",
            description="test",
            parameters={"type": "object", "properties": {}},
            handler=handler,
        )
    )
    executor = ToolExecutor(registry, timeout=5.0)

    class FakeLLM:
        def base_system_prompt(self, **kwargs):
            return "You are Maya."

        def complete(self, messages, tools=None, model=None, max_tokens=None):
            if tools:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="tc1",
                            name="imagine_generate",
                            arguments={"prompt": "party dog"},
                            raw_arguments="{}",
                        ),
                        ToolCall(
                            id="tc2",
                            name="imagine_generate",
                            arguments={"prompt": "party dog"},
                            raw_arguments="{}",
                        ),
                    ],
                )
            return LLMResponse(content="done")

        def stream_messages(self, messages, model=None):
            yield "double dog energy"

    loop = ToolLoop(FakeLLM(), registry, executor, max_rounds=2, mode="native")
    settings = {"imagine": {"remark_enabled": True}}
    with (
        patch("services.imagine.remark.remark_enabled", return_value=True),
        patch("services.settings.store.load_effective_settings", return_value=settings),
        patch("services.imagine.tool_context.get_imagine_tool_context", return_value={}),
    ):
        result = loop.run(
            [{"role": "system", "content": "sys"}, {"role": "user", "content": "draw party dog"}],
        )
    assert len(calls) == 1
    assert len(result.trace) == 2
    assert result.trace[0]["result"] == result.trace[1]["result"]
    assert "dog" in result.final_text.lower()

