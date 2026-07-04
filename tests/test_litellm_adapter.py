"""Tests for LiteLLMAdapter API parity with LLMClient."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_VOICE_RUNTIME = Path(__file__).resolve().parents[1] / "packages" / "voice-runtime"
if str(_VOICE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_VOICE_RUNTIME))

from services.llm.litellm_adapter import LiteLLMAdapter


def _chunk(content: str):
    delta = MagicMock()
    delta.content = content
    choice = MagicMock()
    choice.delta = delta
    chunk = MagicMock()
    chunk.choices = [choice]
    chunk.id = "chunk-1"
    return chunk


def test_stream_messages_passes_model_override() -> None:
    adapter = LiteLLMAdapter(litellm_model="gemini/gemini-2.0-flash")
    messages = [{"role": "user", "content": "look at this image"}]
    vision_model = "openrouter/minimax/minimax-m3"

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = iter([_chunk("what a dog")])

        tokens = list(adapter.stream_messages(messages, model=vision_model))

    assert tokens == ["what a dog"]
    mock_completion.assert_called_once()
    kwargs = mock_completion.call_args.kwargs
    assert kwargs["model"] == vision_model
    assert kwargs["stream"] is True


def test_stream_messages_defaults_to_litellm_model() -> None:
    adapter = LiteLLMAdapter(litellm_model="gemini/gemini-2.0-flash")
    messages = [{"role": "user", "content": "hello"}]

    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = iter([_chunk("hi")])

        list(adapter.stream_messages(messages))

    kwargs = mock_completion.call_args.kwargs
    assert kwargs["model"] == "gemini/gemini-2.0-flash"
