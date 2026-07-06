"""Access the live VoiceAgent LLM from service-layer code."""

from __future__ import annotations

from typing import Any

_agent_llm: Any | None = None


def set_agent_llm(llm: Any) -> None:
    global _agent_llm
    _agent_llm = llm


def get_agent_llm() -> Any | None:
    return _agent_llm
