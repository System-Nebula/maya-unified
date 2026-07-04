"""Tests for desktop vision capture helpers."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
VOICE_RUNTIME = ROOT / "packages" / "voice-runtime"
if str(VOICE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(VOICE_RUNTIME))

TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

from services.llm.health import build_agent_capabilities
from services.voice import vision_frames
from vision import (
    build_user_content,
    is_vision_followup,
    is_vision_request,
    model_supports_vision,
    resolve_vision_user_content,
    wants_vision,
)


def test_is_vision_request_positive():
    assert is_vision_request("what's on my screen right now?")
    assert is_vision_request("can you look at this window")
    assert is_vision_request("take a screenshot and tell me")
    assert is_vision_request("use my screen and tell me what tabs I have open")
    assert is_vision_request("what do you see on my screen?")


def test_is_vision_followup():
    assert is_vision_followup("yeah can you please name some")
    assert is_vision_followup("that's not true, look again")
    assert not is_vision_followup("play creepy nuts on discord")


def test_wants_vision_followup_with_frame():
    vision_frames.clear_frame("op-fu")
    vision_frames.put_frame("op-fu", TINY_PNG_B64)
    assert wants_vision("please name some", "op-fu")
    assert not wants_vision("hello there", "op-fu")
    vision_frames.clear_frame("op-fu")


def test_is_vision_request_negative():
    assert not is_vision_request("hello maya")
    assert not is_vision_request("play some music on discord")
    assert not is_vision_request("")


def test_model_supports_vision_auto():
    assert model_supports_vision("google/gemma-3-12b-it", {})
    assert model_supports_vision("qwen2-vl-7b", {})
    assert not model_supports_vision("llama-3.1-8b-instruct", {})


def test_model_supports_vision_override():
    assert model_supports_vision("llama-3.1-8b", {"vision_capable": True})
    assert not model_supports_vision("gemma-3-vision", {"vision_capable": False})


def test_build_user_content_shape():
    content = build_user_content(
        "describe this",
        "data:image/png;base64,abc",
        reasoning={"provider": "litellm"},
    )
    assert isinstance(content, list)
    assert content[0]["type"] == "image_url"
    assert content[1]["type"] == "text"
    assert content[0]["image_url"]["url"] == "data:image/png;base64,abc"
    assert "detail" not in content[0]["image_url"]


def test_build_user_content_lm_studio_data_uri():
    content = build_user_content(
        "describe this",
        "data:image/png;base64,abc123",
        reasoning={"provider": "lm_studio"},
    )
    assert content[0]["image_url"]["url"] == "data:image/png;base64,abc123"


def test_build_user_content_wraps_raw_base64():
    content = build_user_content("describe", "abc123", reasoning={"provider": "lm_studio"})
    assert content[0]["image_url"]["url"] == "data:image/png;base64,abc123"


def test_vision_frames_put_get_clear():
    vision_frames.clear_frame("op-test")
    result = vision_frames.put_frame("op-test", TINY_PNG_B64, label="Chrome")
    assert result["ok"] is True
    status = vision_frames.status_for("op-test")
    assert status["active"] is True
    assert status["label"] == "Chrome"
    frame = vision_frames.get_frame("op-test")
    assert frame is not None
    assert frame.startswith("data:image/png;base64,")
    vision_frames.clear_frame("op-test")
    assert vision_frames.get_frame("op-test") is None


def test_vision_frames_ttl_expiry():
    vision_frames.clear_frame("op-ttl")
    vision_frames.put_frame("op-ttl", TINY_PNG_B64)
    frame = vision_frames._frames.get("op-ttl")
    assert frame is not None
    frame.captured_at = time.monotonic() - vision_frames.TTL_S - 1
    assert vision_frames.get_frame("op-ttl") is None


def test_vision_frames_rejects_oversized():
    vision_frames.clear_frame("op-big")
    huge = "x" * (vision_frames.MAX_FRAME_BYTES + 1)
    result = vision_frames.put_frame("op-big", huge)
    assert result["ok"] is False


def test_resolve_vision_user_content_with_frame():
    vision_frames.clear_frame("op-vis")
    vision_frames.put_frame("op-vis", TINY_PNG_B64)
    reasoning = {"model": "gemma-3-vision", "vision_capable": "auto"}
    content = resolve_vision_user_content(
        "user asked",
        "what is on my screen?",
        "op-vis",
        reasoning,
    )
    assert isinstance(content, list)
    assert content[0]["type"] == "image_url"
    assert content[1]["type"] == "text"
    vision_frames.clear_frame("op-vis")


def test_resolve_vision_followup_with_frame():
    vision_frames.clear_frame("op-fu2")
    vision_frames.put_frame("op-fu2", TINY_PNG_B64)
    reasoning = {"model": "gemma-3-vision", "provider": "lm_studio"}
    content = resolve_vision_user_content(
        "please name some",
        "please name some",
        "op-fu2",
        reasoning,
    )
    assert isinstance(content, list)
    vision_frames.clear_frame("op-fu2")


def test_resolve_vision_user_content_no_frame_hint():
    vision_frames.clear_frame("op-noframe")
    reasoning = {"model": "gemma-3-vision"}
    content = resolve_vision_user_content(
        "hello",
        "look at my screen",
        "op-noframe",
        reasoning,
    )
    assert isinstance(content, str)
    assert "Share screen" in content


def test_build_agent_capabilities_vision():
    health = {"status": "ok", "model": "google/gemma-3-12b-it"}
    reasoning = {"provider": "litellm", "litellm": {"model": "google/gemma-3-12b-it"}}
    caps = build_agent_capabilities(voice_ready=True, health=health, reasoning=reasoning)
    assert caps["vision"] is True

    caps_no = build_agent_capabilities(
        voice_ready=True,
        health={"status": "ok", "model": "llama-3.1-8b"},
        reasoning={"provider": "lm_studio", "model": "llama-3.1-8b"},
    )
    assert caps_no["vision"] is False


def test_agent_build_messages_attaches_vision():
    from agent import VoiceAgent

    vision_frames.clear_frame("op-agent")
    vision_frames.put_frame("op-agent", TINY_PNG_B64)

    class StubAgent:
        memory = None
        history = []
        _session_prefix = ""
        _post_history_instructions = ""
        _vision_operator_id = "op-agent"
        _vision_reasoning = {"model": "gemma-3-vision", "vision_capable": "auto"}

        def __init__(self):
            self.llm = MagicMock()
            self.llm.base_system_prompt.return_value = "system"

        def _tools_active(self):
            return False

        def _discord_tool_hint(self, _t):
            return ""

        def _web_tool_hint(self, _t):
            return ""

    messages = VoiceAgent._build_messages(StubAgent(), "what is on my screen?")
    user_msg = messages[-1]
    assert user_msg["role"] == "user"
    assert isinstance(user_msg["content"], list)
    assert user_msg["content"][0]["type"] == "image_url"
    vision_frames.clear_frame("op-agent")
