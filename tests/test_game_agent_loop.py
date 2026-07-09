"""Tests for game agent_loop vision + narration."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_VR = _ROOT / "packages" / "voice-runtime"
if str(_VR) not in sys.path:
    sys.path.insert(0, str(_VR))

from services.game.agent_loop import _vision_complete  # noqa: E402
from services.game.narration import speak_game_line  # noqa: E402
import services.voice.hub  # noqa: E402


def test_vision_complete_uses_llm_complete():
    mock_resp = MagicMock()
    mock_resp.content = '{"action": "wait", "say": "hi", "goal_reached": false, "goal_progress": ""}'
    mock_resp.reasoning_content = ""
    mock_client = MagicMock()
    mock_client.complete.return_value = mock_resp

    messages = [{"role": "user", "content": "pick"}]
    with patch("services.game.agent_loop._vision_llm_client", return_value=mock_client), patch(
        "services.game.agent_loop._resolve_vision_model", return_value="gemini/gemini-2.0-flash"
    ), patch(
        "services.game.agent_loop._vision_policy",
        return_value={
            "enable_thinking": False,
            "max_tokens": 400,
            "reasoning_effort": None,
            "timeout_s": 55.0,
        },
    ):
        raw = _vision_complete(messages, "op-1")

    assert "wait" in raw
    mock_client.complete.assert_called_once()
    kwargs = mock_client.complete.call_args.kwargs
    assert kwargs.get("model") == "gemini/gemini-2.0-flash"
    assert kwargs.get("max_tokens") == 400


def test_vision_complete_enables_thinking_from_profile():
    mock_resp = MagicMock()
    mock_resp.content = '{"action": "press_down", "say": "", "goal_reached": false, "goal_progress": ""}'
    mock_resp.reasoning_content = ""
    mock_client = MagicMock()
    mock_client.complete.return_value = mock_resp

    messages = [{"role": "user", "content": "pick"}]
    with patch("services.game.agent_loop._vision_llm_client", return_value=mock_client), patch(
        "services.game.agent_loop._resolve_vision_model", return_value="gemini/gemini-2.0-flash"
    ), patch(
        "services.game.agent_loop._vision_policy",
        return_value={
            "enable_thinking": True,
            "max_tokens": 1200,
            "reasoning_effort": "low",
            "timeout_s": 90.0,
        },
    ):
        raw = _vision_complete(messages, "op-1", profile_id="pokemon_gba", purpose="turn")

    assert "press_down" in raw
    kwargs = mock_client.complete.call_args.kwargs
    assert kwargs.get("enable_thinking") is True
    assert kwargs.get("reasoning_effort") == "on"
    assert kwargs.get("max_tokens") == 1200


def test_vision_probe_never_enables_thinking():
    mock_resp = MagicMock()
    mock_resp.content = '{"trap": "none", "has_text_box": false}'
    mock_resp.reasoning_content = ""
    mock_client = MagicMock()
    mock_client.complete.return_value = mock_resp

    with patch("services.game.agent_loop._vision_llm_client", return_value=mock_client), patch(
        "services.game.agent_loop._resolve_vision_model", return_value="gemma"
    ), patch(
        "services.game.agent_loop._vision_policy",
        return_value={
            "enable_thinking": True,
            "max_tokens": 1200,
            "reasoning_effort": "on",
            "think_prefix": "",
            "timeout_s": 90.0,
        },
    ):
        _vision_complete([{"role": "user", "content": "x"}], "op", purpose="probe")

    kwargs = mock_client.complete.call_args.kwargs
    assert kwargs.get("enable_thinking") is False
    assert kwargs.get("reasoning_effort") == "off"


def test_strip_thinking_content_gemma_channel():
    from services.game.agent_loop import _strip_thinking_content

    raw = "<|channel|>thoughtNES loop — walk away.<channel|>\n{\"action\": \"press_down\"}"
    cleaned = _strip_thinking_content(raw)
    assert cleaned.startswith("{")
    assert "press_down" in cleaned


def test_speak_game_line_runs_in_thread():
    mock_hub = MagicMock()
    mock_hub.ready = True
    mock_hub.agent = MagicMock()

    with patch("services.voice.hub.hub", mock_hub), patch(
        "services.game.narration.threading.Thread"
    ) as thread_cls:
        thread_cls.return_value = MagicMock()
        speak_game_line("Walking north.", operator_id="op-1")

        thread_cls.assert_called_once()
        target = thread_cls.call_args.kwargs.get("target") or thread_cls.call_args[0][0]
        target()
        mock_hub.speak_text.assert_called_once_with("Walking north.", operator_id="op-1")
