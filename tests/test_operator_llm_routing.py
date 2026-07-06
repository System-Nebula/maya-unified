"""Operator LLM routing during voice turns."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VOICE_RUNTIME = ROOT / "packages" / "voice-runtime"
if str(VOICE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(VOICE_RUNTIME))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.llm.litellm_adapter import LiteLLMAdapter


def test_litellm_adapter_uses_active_operator_model(monkeypatch):
    import types
    from services.llm import provider

    class FakeHub:
        _active_operator_id = "op-123"

    monkeypatch.setattr(
        provider,
        "_reasoning_settings",
        lambda operator_id=None: {
            "provider": "litellm",
            "litellm": {"mode": "sdk", "model": "openrouter/deepseek/deepseek-v4-flash"},
        },
    )
    fake_hub_mod = types.ModuleType("services.voice.hub")
    fake_hub_mod.hub = FakeHub()
    monkeypatch.setitem(sys.modules, "services.voice.hub", fake_hub_mod)

    adapter = LiteLLMAdapter(litellm_model="gemini/gemini-2.0-flash")
    assert adapter._effective_model() == "openrouter/deepseek/deepseek-v4-flash"
