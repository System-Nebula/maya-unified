"""Normalize reasoning provider / LiteLLM fields for consistent LLM routing."""

from __future__ import annotations

from typing import Any

_LITELLM_PREFIXES = frozenset({
    "gemini",
    "openai",
    "openrouter",
    "anthropic",
    "ollama",
    "groq",
    "azure",
    "cohere",
    "mistral",
    "deepseek",
    "xai",
})


def looks_like_litellm_model(model: str) -> bool:
    """True when model id uses provider/model form (e.g. gemini/gemini-2.0-flash)."""
    raw = (model or "").strip()
    if "/" not in raw:
        return False
    prefix = raw.split("/", 1)[0].lower()
    return prefix in _LITELLM_PREFIXES


def is_litellm_sdk(reasoning: dict[str, Any] | None) -> bool:
    if not isinstance(reasoning, dict):
        return False
    if str(reasoning.get("provider", "")).lower() != "litellm":
        return False
    litellm = reasoning.get("litellm") or {}
    return str(litellm.get("mode", "sdk")).lower() != "proxy"


def normalize_reasoning(reasoning: dict[str, Any] | None) -> dict[str, Any]:
    """Align provider, model, and litellm block so create_llm_client routes correctly."""
    if not isinstance(reasoning, dict):
        return {}
    out = dict(reasoning)
    litellm = dict(out.get("litellm") or {})
    out["litellm"] = litellm
    provider = str(out.get("provider", "lm_studio")).lower()
    mode = str(litellm.get("mode", "sdk")).lower()
    litellm_model = str(litellm.get("model") or "").strip()

    if provider == "litellm":
        if mode == "sdk" and litellm_model:
            out["model"] = litellm_model
        return out

    if mode == "sdk" and litellm_model and looks_like_litellm_model(litellm_model):
        out["provider"] = "litellm"
        out["model"] = litellm_model
    return out
