"""LiteLLM-backed LLM client matching qwen3 LLMClient surface."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Iterator

from config import CONFIG, LLMConfig
from llm import AUTO_INSTRUCT_GUIDE, LLMResponse, ToolCall, ToolsUnsupported, sanitize_llm_output

_CONTROL_TOKEN_RE = re.compile(r"\s*/no[-_]think\b", re.I)
_PLACEHOLDER_API_KEYS = frozenset({"", "lm-studio", "vllm-local", "local-model"})


def _effective_api_key(api_key: str | None) -> str | None:
    key = (api_key or "").strip()
    if key.lower() in _PLACEHOLDER_API_KEYS:
        return None
    return key or None


@dataclass
class LiteLLMSettings:
    model: str
    api_key: str = ""
    temperature: float = 0.6
    top_p: float = 0.9
    max_tokens: int = 220


class LiteLLMAdapter:
  """Drop-in replacement for LLMClient when reasoning.provider == litellm."""

  def __init__(self, cfg: LLMConfig | None = None, *, litellm_model: str | None = None):
      self.cfg = cfg or CONFIG.llm
      self.litellm_model = litellm_model or self.cfg.model

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

  def _completion_kwargs(self, messages: list[dict], *, stream: bool, max_tokens: int | None, model: str | None):
      resolved_model = model or self.litellm_model
      kwargs = dict(
          model=resolved_model,
          messages=messages,
          stream=stream,
          temperature=self.cfg.temperature,
          top_p=self.cfg.top_p,
          max_tokens=max_tokens or self.cfg.max_tokens,
          api_key=_effective_api_key(self.cfg.api_key),
      )
      model_lc = resolved_model.lower()
      effort = (self.cfg.reasoning_effort or "").strip().lower()
      if "deepseek-v4" in model_lc:
          extra = dict(kwargs.get("extra_body") or {})
          reasoning = dict(extra.get("reasoning") or {})
          if effort in ("none", "minimal", "low", "medium", "high", "xhigh"):
              reasoning["effort"] = effort
          elif self.cfg.disable_thinking:
              reasoning["effort"] = "none"
          if reasoning:
              extra["reasoning"] = reasoning
              kwargs["extra_body"] = extra
      return kwargs

  def stream_reply(self, user_text: str, history: list[dict] | None = None) -> Iterator[str]:
      import litellm

      messages = [{"role": "system", "content": self.base_system_prompt()}]
      if history:
          keep = self.cfg.history_turns * 2
          messages.extend(history[-keep:])
      messages.append({"role": "user", "content": user_text})
      resp = litellm.completion(**self._completion_kwargs(messages, stream=True, max_tokens=None, model=None))
      for chunk in resp:
          try:
              delta = chunk.choices[0].delta.content
          except (AttributeError, IndexError, TypeError):
              delta = None
          if delta:
              yield delta

  def stream_messages(self, messages: list[dict]) -> Iterator[str]:
      import litellm

      resp = litellm.completion(**self._completion_kwargs(messages, stream=True, max_tokens=None, model=None))
      for chunk in resp:
          try:
              delta = chunk.choices[0].delta.content
          except (AttributeError, IndexError, TypeError):
              delta = None
          if delta:
              yield delta

  def complete(
      self,
      messages: list[dict],
      tools: list[dict] | None = None,
      model: str | None = None,
      max_tokens: int | None = None,
  ) -> LLMResponse:
      import litellm

      kwargs = self._completion_kwargs(messages, stream=False, max_tokens=max_tokens, model=model)
      if tools:
          kwargs["tools"] = tools
          kwargs["tool_choice"] = "auto"
      try:
          resp = litellm.completion(**kwargs)
      except Exception as exc:  # noqa: BLE001
          if tools:
              raise ToolsUnsupported(str(exc)) from exc
          raise
      if not resp.choices:
          return LLMResponse()
      msg = resp.choices[0].message
      out = LLMResponse(content=sanitize_llm_output((getattr(msg, "content", None) or "").strip()))
      for tc in getattr(msg, "tool_calls", None) or []:
          raw = tc.function.arguments or "{}"
          try:
              parsed = json.loads(raw)
          except (TypeError, ValueError):
              parsed = {}
          out.tool_calls.append(
              ToolCall(
                  id=tc.id or tc.function.name,
                  name=tc.function.name,
                  arguments=parsed if isinstance(parsed, dict) else {},
                  raw_arguments=raw,
              )
          )
      return out
