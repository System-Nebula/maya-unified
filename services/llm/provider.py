"""Factory for server-side LLM clients (LM Studio vs LiteLLM)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from services.settings.store import load_settings

if TYPE_CHECKING:
    from llm import LLMClient


def get_provider_name() -> str:
    return str(load_settings().get("reasoning", {}).get("provider", "lm_studio"))


def create_llm_client():
    """Return an LLMClient-compatible object for VoiceAgent."""
    settings = load_settings()
    reasoning = settings.get("reasoning", {})
    provider = str(reasoning.get("provider", "lm_studio"))

    if provider == "litellm":
        from services.llm.litellm_adapter import LiteLLMAdapter

        litellm_cfg = reasoning.get("litellm") or {}
        mode = str(litellm_cfg.get("mode", "sdk"))
        if mode == "proxy":
            from llm import LLMClient

            return LLMClient()
        model = str(litellm_cfg.get("model") or reasoning.get("model", "gemini/gemini-2.0-flash"))
        return LiteLLMAdapter(litellm_model=model)

    from llm import LLMClient

    return LLMClient()


def swap_agent_llm(agent) -> None:
    """Replace agent.llm after settings change."""
    agent.llm = create_llm_client()
    if getattr(agent, "memory", None) is not None and hasattr(agent.memory, "llm"):
        agent.memory.llm = agent.llm
