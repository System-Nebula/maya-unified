"""LiteLLM-backed LLM client matching qwen3 LLMClient surface."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Iterator

from config import CONFIG, LLMConfig
from llm import (
    AUTO_INSTRUCT_GUIDE,
    LLMClient,
    LLMResponse,
    ToolCall,
    ToolsUnsupported,
    sanitize_llm_output,
)

from services.llm.api_keys import is_placeholder_api_key, resolve_reasoning_api_key

_CONTROL_TOKEN_RE = re.compile(r"\s*/no[-_]think\b", re.I)
_PLACEHOLDER_API_KEYS = frozenset({"", "lm-studio", "vllm-local", "local-model"})


def _effective_api_key(api_key: str | None) -> str | None:
    key = (api_key or "").strip()
    if is_placeholder_api_key(key):
        try:
            from services.settings.store import load_effective_settings
            from services.voice.hub import hub

            oid = getattr(hub, "_active_operator_id", None)
            settings = load_effective_settings(str(oid) if oid else None)
            resolved = resolve_reasoning_api_key(
                settings.get("reasoning", {}),
                operator_id=str(oid) if oid else None,
            )
            if not is_placeholder_api_key(resolved):
                return resolved
        except Exception:  # noqa: BLE001
            pass
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
      self.last_completion_id: str | None = None

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

  def _effective_model(self) -> str:
      """Resolve at call time so operator settings apply without full agent reload."""
      try:
          from services.llm.provider import _reasoning_settings
          from services.voice.hub import hub

          oid = getattr(hub, "_active_operator_id", None)
          reasoning = _reasoning_settings(operator_id=str(oid) if oid else None)
          if str(reasoning.get("provider", "")).lower() == "litellm":
              litellm_cfg = reasoning.get("litellm") or {}
              model = str(litellm_cfg.get("model") or reasoning.get("model") or "").strip()
              if model:
                  return model
      except Exception:  # noqa: BLE001
          pass
      return self.litellm_model or self.cfg.model

  def _completion_kwargs(
      self,
      messages: list[dict],
      *,
      stream: bool,
      max_tokens: int | None,
      model: str | None,
      enable_thinking: bool | None = None,
      reasoning_effort: str | None = None,
      response_format: dict | None = None,
  ):
      resolved_model = model or self._effective_model()
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
      thinking_off = self.cfg.disable_thinking if enable_thinking is None else (not enable_thinking)
      effort = (reasoning_effort or self.cfg.reasoning_effort or "").strip().lower()
      if "deepseek-v4" in model_lc or enable_thinking is True or effort:
          extra = dict(kwargs.get("extra_body") or {})
          reasoning = dict(extra.get("reasoning") or {})
          if effort in ("none", "minimal", "low", "medium", "high", "xhigh"):
              reasoning["effort"] = effort
          elif enable_thinking is True:
              reasoning["effort"] = "medium"
          elif thinking_off:
              reasoning["effort"] = "none"
          if reasoning:
              extra["reasoning"] = reasoning
              kwargs["extra_body"] = extra
      if response_format:
          kwargs["response_format"] = response_format
      return kwargs

  def stream_reply(self, user_text: str, history: list[dict] | None = None) -> Iterator[str]:
      import litellm

      messages = [{"role": "system", "content": self.base_system_prompt()}]
      if history:
          keep = self.cfg.history_turns * 2
          messages.extend(history[-keep:])
      messages.append({"role": "user", "content": user_text})
      resp = litellm.completion(**self._completion_kwargs(messages, stream=True, max_tokens=None, model=None))
      self.last_completion_id = None
      for chunk in resp:
          chunk_id = getattr(chunk, "id", None)
          if chunk_id:
              self.last_completion_id = str(chunk_id)
          try:
              delta = chunk.choices[0].delta.content
          except (AttributeError, IndexError, TypeError):
              delta = None
          if delta:
              yield delta

  def stream_messages(
      self,
      messages: list[dict],
      *,
      model: str | None = None,
  ) -> Iterator[str]:
      import litellm

      resp = litellm.completion(**self._completion_kwargs(messages, stream=True, max_tokens=None, model=model))
      self.last_completion_id = None
      for chunk in resp:
          chunk_id = getattr(chunk, "id", None)
          if chunk_id:
              self.last_completion_id = str(chunk_id)
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
      *,
      enable_thinking: bool | None = None,
      reasoning_effort: str | None = None,
      response_format: dict | None = None,
  ) -> LLMResponse:
      import logging

      import litellm

      log = logging.getLogger("llm")
      kwargs = self._completion_kwargs(
          messages,
          stream=False,
          max_tokens=max_tokens,
          model=model,
          enable_thinking=enable_thinking,
          reasoning_effort=reasoning_effort,
          response_format=response_format,
      )
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
          log.warning("LLM complete returned no choices")
          return LLMResponse()
      msg = resp.choices[0].message
      content = sanitize_llm_output(LLMClient._message_text(msg))
      reasoning_raw = getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None)
      reasoning_content = (
          sanitize_llm_output(reasoning_raw.strip())
          if isinstance(reasoning_raw, str) and reasoning_raw.strip()
          else ""
      )
      if not content:
          finish = getattr(resp.choices[0], "finish_reason", None)
          log.warning("LLM complete returned empty content (finish_reason=%s)", finish)
      out = LLMResponse(content=content, reasoning_content=reasoning_content)
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
