"""Tests for post-imagine remark helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.imagine.remark import (
    _vision_available,
    artifact_from_tool_result,
    build_remark_messages,
    emit_imagine_artifact,
    finish_imagine_tool_remark,
    parse_imagine_tool_result,
    remark_enabled,
    remark_vision_model,
    resolve_imagine_output_path,
    stream_remark_text,
)
from services.imagine.settings import DEFAULT_REMARK_VISION_MODEL


def test_resolve_imagine_output_path_maps_prefix(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MAYA_IMAGE_ROOT", str(tmp_path))
    img = tmp_path / "outputs" / "2026-07-04" / "abc.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"png")
    resolved = resolve_imagine_output_path("/imagine-outputs/outputs/2026-07-04/abc.png")
    assert resolved == img.resolve()


def test_resolve_imagine_output_path_rejects_escape(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MAYA_IMAGE_ROOT", str(tmp_path))
    assert resolve_imagine_output_path("/imagine-outputs/../../etc/passwd") is None


def test_build_remark_messages_text_only_when_no_image(monkeypatch) -> None:
    monkeypatch.setenv("MAYA_IMAGE_ROOT", "/nonexistent")
    artifact = {"url": "/imagine-outputs/missing.png", "model": "Z-Image Turbo"}
    messages, vision_used = build_remark_messages(
        prompt="sunset over mountains",
        artifact=artifact,
        system_prompt="You are Maya.",
        use_vision=False,
    )
    assert vision_used is False
    assert messages[0]["role"] == "system"
    user = messages[1]["content"]
    assert isinstance(user, str)
    assert "sunset over mountains" in user
    assert "Z-Image Turbo" in user


def test_build_remark_messages_includes_image_part(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MAYA_IMAGE_ROOT", str(tmp_path))
    rel = Path("outputs/test.png")
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\x89PNG\r\n")
    artifact = {"url": f"/imagine-outputs/{rel.as_posix()}", "model": "Krea 2 Turbo"}
    settings = {"imagine": {"remark_vision_model": "openrouter/google/gemini-2.0-flash-001"}}
    messages, vision_used = build_remark_messages(
        prompt="a stupid dog",
        artifact=artifact,
        system_prompt="You are Maya.",
        settings=settings,
    )
    assert vision_used is True
    user = messages[1]["content"]
    assert isinstance(user, list)
    assert user[0]["type"] == "text"
    assert user[1]["type"] == "image_url"
    assert user[1]["image_url"]["url"].startswith("data:image/")


def test_vision_available_requires_explicit_remark_vision_model(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MAYA_IMAGE_ROOT", str(tmp_path))
    rel = Path("outputs/test.png")
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\x89PNG\r\n")
    settings = {"reasoning": {"litellm": {"model": "openrouter/some-text-model"}}}
    assert remark_vision_model(settings) == ""
    assert _vision_available(settings) is False
    messages, vision_used = build_remark_messages(
        prompt="a dog",
        artifact={"url": f"/imagine-outputs/{rel.as_posix()}", "model": "Krea 2 Turbo"},
        system_prompt="You are Maya.",
        settings=settings,
    )
    assert vision_used is False
    assert isinstance(messages[1]["content"], str)


def test_finish_imagine_tool_remark_retries_text_only_on_vision_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MAYA_IMAGE_ROOT", str(tmp_path))
    rel = Path("outputs/x.png")
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\x89PNG\r\n")
    tool_result = json.dumps(
        {
            "ok": True,
            "url": f"/imagine-outputs/{rel.as_posix()}",
            "job_id": "j1",
            "prompt": "party dog",
            "model": "Krea 2 Turbo",
            "model_key": "krea2",
        }
    )
    settings = {"imagine": {"remark_vision_model": "vision/model", "remark_enabled": True}}
    calls: list[bool] = []

    class FakeLLM:
        def base_system_prompt(self, **kwargs):
            return "You are Maya."

        def stream_messages(self, messages, model=None):
            calls.append(isinstance(messages[1]["content"], list))
            if calls[-1]:
                raise RuntimeError("No endpoints found that support image input")
            yield "absolute menace of a dog"

    remark = finish_imagine_tool_remark(
        FakeLLM(),
        [{"role": "user", "content": "draw a dog"}],
        tool_result,
        system_prompt="You are Maya.",
        settings=settings,
        emit=None,
    )
    assert remark == "absolute menace of a dog"
    assert calls == [True, False]


def test_stream_remark_text_requires_adapter_model_kwarg_for_vision() -> None:
    """Vision remarks pass model=; adapters must accept it (LiteLLMAdapter regression)."""

    class OldAdapterLLM:
        def stream_messages(self, messages):
            yield "should not run"

    with pytest.raises(TypeError):
        list(
            stream_remark_text(
                OldAdapterLLM(),
                [{"role": "user", "content": "look at this"}],
                vision_model=DEFAULT_REMARK_VISION_MODEL,
            )
        )


def test_stream_remark_text_passes_minimax_vision_model() -> None:
    models_used: list[str | None] = []

    class FakeLLM:
        def stream_messages(self, messages, model=None):
            models_used.append(model)
            yield "that dog looks ridiculous"

    remark = stream_remark_text(
        FakeLLM(),
        [{"role": "user", "content": "look at this"}],
        vision_model=DEFAULT_REMARK_VISION_MODEL,
    )
    assert remark == "that dog looks ridiculous"
    assert models_used == [DEFAULT_REMARK_VISION_MODEL]


def test_remark_vision_model_reads_minimax_from_settings() -> None:
    settings = {"imagine": {"remark_vision_model": DEFAULT_REMARK_VISION_MODEL}}
    assert remark_vision_model(settings) == "openrouter/minimax/minimax-m3"
    assert _vision_available(settings) is True


def test_parse_imagine_tool_result() -> None:
    ok = '{"ok": true, "url": "/imagine-outputs/x.png", "prompt": "cat"}'
    assert parse_imagine_tool_result(ok) is not None
    assert parse_imagine_tool_result('{"ok": false}') is None


def test_remark_enabled_env_override(monkeypatch) -> None:
    monkeypatch.setenv("MAYA_IMAGINE_REMARK", "0")
    assert remark_enabled({"imagine": {"remark_enabled": True}}) is False
    monkeypatch.setenv("MAYA_IMAGINE_REMARK", "1")
    assert remark_enabled({"imagine": {"remark_enabled": False}}) is True


def test_artifact_from_tool_result() -> None:
    data = {
        "ok": True,
        "url": "/imagine-outputs/a.png",
        "job_id": "j1",
        "model": "Z-Image Turbo",
        "model_key": "z-image-turbo",
        "workflow_name": "z-image-turbo-t2i",
        "gen_ms": 1200,
        "prompt": "dog",
    }
    artifact = artifact_from_tool_result(data)
    assert artifact["type"] == "image"
    assert artifact["prompt"] == "dog"


def test_emit_imagine_artifact_broadcasts_meta() -> None:
    emitted: list[dict] = []

    def emit(**kwargs):
        emitted.append(kwargs)

    data = {
        "ok": True,
        "url": "/imagine-outputs/a.png",
        "job_id": "j1",
        "model": "Z-Image Turbo",
        "model_key": "z-image-turbo",
        "workflow_id": "wf-1",
        "workflow_name": "z-image-turbo-t2i",
        "gen_ms": 1200,
        "prompt": "dog",
    }
    artifact = emit_imagine_artifact(data, emit)
    assert artifact["type"] == "image"
    assert len(emitted) == 1
    assert emitted[0]["type"] == "ai"
    assert emitted[0]["artifacts"][0]["url"] == "/imagine-outputs/a.png"
    assert emitted[0]["job_id"] == "j1"
    assert emitted[0]["model"] == "Z-Image Turbo"
