"""LLM client that delegates inference to the browser via WebLLM."""

from __future__ import annotations

from typing import Iterator

from config import CONFIG, LLMConfig
from llm import AUTO_INSTRUCT_GUIDE, LLMResponse, ToolsUnsupported, sanitize_llm_output

from services.llm import webllm_broker
from services.settings.store import load_settings


def _normalize_messages_for_webllm(messages: list[dict], *, fallback_system: str = "") -> list[dict]:
    """WebLLM accepts exactly one system message and it must be first."""
    system_chunks: list[str] = []
    rest: list[dict] = []

    for msg in messages or []:
        role = str(msg.get("role", "")).lower()
        if role == "system":
            text = str(msg.get("content") or "").strip()
            if text:
                system_chunks.append(text)
            continue
        if role == "tool":
            rest.append({
                "role": "user",
                "content": (
                    f"Tool result ({msg.get('tool_call_id', 'tool')}):\n"
                    f"{msg.get('content', '')}"
                ),
            })
            continue
        if role == "assistant":
            parts: list[str] = []
            content = str(msg.get("content") or "").strip()
            if content:
                parts.append(content)
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                parts.append(f"Tool calls: {tool_calls}")
            rest.append({"role": "assistant", "content": "\n".join(parts)})
            continue
        if role == "user":
            rest.append({"role": "user", "content": str(msg.get("content") or "")})

    system_text = "\n\n".join(system_chunks).strip() or str(fallback_system or "").strip()
    if not system_text:
        system_text = "You are a helpful assistant."
    # Small browser models choke on Maya's full persona + tool guide — keep headroom.
    if len(system_text) > 3500:
        system_text = system_text[:3500].rstrip() + "\n\n[Context truncated for WebLLM.]"

    # Keep recent turns only — 1.5B/3B models lose coherence with long threads.
    if len(rest) > 10:
        rest = rest[-10:]

    normalized: list[dict] = [{"role": "system", "content": system_text}]
    normalized.extend(rest)
    if len(normalized) == 1:
        normalized.append({"role": "user", "content": "Continue."})
    return normalized


def webllm_prefers_direct_chat(model_id: str) -> bool:
    """Tiny WebLLM models can't reliably run the tool JSON loop."""
    mid = (model_id or "").upper()
    return any(tag in mid for tag in ("1.5B", "3B-INSTRUCT", "3.2-3B", "PHI-3.5-MINI"))


class WebLLMBridgeClient:
    """Drop-in LLMClient surface backed by in-browser @mlc-ai/web-llm."""

    def __init__(self, cfg: LLMConfig | None = None):
        self.cfg = cfg or CONFIG.llm
        self._model_id = self._webllm_model_id()
        self.last_completion_id: str | None = None

    def prefers_direct_chat(self) -> bool:
        return webllm_prefers_direct_chat(self._model_id)

    def _webllm_model_id(self) -> str:
        settings = load_settings()
        webllm = settings.get("reasoning", {}).get("webllm") or {}
        return str(webllm.get("model_id") or "Llama-3.1-8B-Instruct-q4f16_1-MLC")

    def base_system_prompt(self, *, include_style_cue: bool = True) -> str:
        system = self.cfg.system_prompt
        if include_style_cue and CONFIG.wants_style_cue():
            system = f"{system}\n\n{AUTO_INSTRUCT_GUIDE}"
        effort = (self.cfg.reasoning_effort or "").strip().lower()
        if (
            self.cfg.disable_thinking
            and self.cfg.no_think_token
            and effort not in ("none", "minimal", "low")
        ):
            system = f"{system} {self.cfg.no_think_token}".strip()
        return system

    def _messages(self, user_text: str, history: list[dict] | None) -> list[dict]:
        messages: list[dict] = [{"role": "system", "content": self.base_system_prompt()}]
        if history:
            keep = self.cfg.history_turns * 2
            messages.extend(history[-keep:])
        messages.append({"role": "user", "content": user_text})
        return messages

    def stream_reply(self, user_text: str, history: list[dict] | None = None) -> Iterator[str]:
        yield from webllm_broker.request_stream(self._messages(user_text, history))

    def stream_messages(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
    ) -> Iterator[str]:
        del model  # WebLLM uses a single in-browser model; vision remarks are disabled.
        normalized = _normalize_messages_for_webllm(
            messages,
            fallback_system=self.base_system_prompt(),
        )
        yield from webllm_broker.request_stream(normalized)

    def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        if tools:
            raise ToolsUnsupported("WebLLM does not support native tool calling")
        normalized = _normalize_messages_for_webllm(
            messages,
            fallback_system=self.base_system_prompt(),
        )
        text = webllm_broker.request_complete(normalized)
        return LLMResponse(content=sanitize_llm_output(text))
