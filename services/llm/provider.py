"""Factory for server-side LLM clients (LM Studio vs LiteLLM)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llm import LLMClient


def _resolve_operator_id(operator_id: str | None = None) -> str | None:
    if operator_id:
        return str(operator_id)
    try:
        from services.voice.hub import hub

        oid = getattr(hub, "_active_operator_id", None)
        return str(oid) if oid else None
    except Exception:  # noqa: BLE001
        return None


def _reasoning_settings(*, operator_id: str | None = None) -> dict:
    """Effective reasoning profile — operator settings override global file."""
    from services.settings.store import load_effective_settings

    settings = load_effective_settings(_resolve_operator_id(operator_id))
    reasoning = settings.get("reasoning")
    return dict(reasoning) if isinstance(reasoning, dict) else {}


def get_provider_name(*, operator_id: str | None = None) -> str:
    return str(_reasoning_settings(operator_id=operator_id).get("provider", "lm_studio"))


def is_webllm_provider(*, operator_id: str | None = None) -> bool:
    return get_provider_name(operator_id=operator_id).lower() == "webllm"


def create_llm_client(*, operator_id: str | None = None):
    """Return an LLMClient-compatible object for VoiceAgent."""
    from services.settings.store import apply_to_config

    reasoning = _reasoning_settings(operator_id=operator_id)
    oid = _resolve_operator_id(operator_id)
    apply_to_config({"reasoning": reasoning}, operator_id=oid)
    provider = str(reasoning.get("provider", "lm_studio"))

    if provider == "webllm":
        from services.llm.webllm_bridge import WebLLMBridgeClient

        return WebLLMBridgeClient()

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


def swap_agent_llm(agent, *, operator_id: str | None = None) -> None:
    """Replace agent.llm after settings change."""
    agent.llm = create_llm_client(operator_id=operator_id)
    if getattr(agent, "memory", None) is not None and hasattr(agent.memory, "llm"):
        agent.memory.llm = agent.llm
    tool_loop = getattr(agent, "tool_loop", None)
    if tool_loop is not None and hasattr(tool_loop, "llm"):
        tool_loop.llm = agent.llm
