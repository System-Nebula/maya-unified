"""LiteLLM provider normalization and routing."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VOICE_RUNTIME = ROOT / "packages" / "voice-runtime"
if str(VOICE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(VOICE_RUNTIME))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.settings.reasoning_normalize import (
    is_litellm_sdk,
    looks_like_litellm_model,
    normalize_reasoning,
)
from services.llm.provider import create_llm_client


def test_normalize_repairs_lm_studio_with_litellm_sdk_block():
    raw = {
        "provider": "lm_studio",
        "model": "google/gemma-4-26b-a4b",
        "litellm": {"mode": "sdk", "model": "gemini/gemini-2.0-flash"},
    }
    out = normalize_reasoning(raw)
    assert out["provider"] == "litellm"
    assert out["model"] == "gemini/gemini-2.0-flash"


def test_is_litellm_sdk():
    assert is_litellm_sdk({"provider": "litellm", "litellm": {"mode": "sdk"}})
    assert not is_litellm_sdk({"provider": "litellm", "litellm": {"mode": "proxy"}})
    assert not is_litellm_sdk({"provider": "lm_studio"})


def test_looks_like_litellm_model():
    assert looks_like_litellm_model("gemini/gemini-2.0-flash")
    assert not looks_like_litellm_model("google/gemma-4-26b-a4b")


def test_create_llm_client_uses_effective_settings(monkeypatch):
    from services.settings import store

    global_settings = {
        "reasoning": {
            "provider": "litellm",
            "litellm": {"mode": "sdk", "model": "gemini/gemini-2.0-flash"},
        }
    }
    operator_settings = {
        "reasoning": {
            "provider": "litellm",
            "litellm": {"mode": "sdk", "model": "openrouter/deepseek/deepseek-v4-flash"},
        }
    }

    monkeypatch.setattr(store, "load_settings", lambda: global_settings)
    monkeypatch.setattr(
        store,
        "load_effective_settings",
        lambda operator_id=None: operator_settings if operator_id else global_settings,
    )

    client = create_llm_client(operator_id="operator-1")
    from services.llm.litellm_adapter import LiteLLMAdapter

    assert isinstance(client, LiteLLMAdapter)
    assert client.litellm_model == "openrouter/deepseek/deepseek-v4-flash"
