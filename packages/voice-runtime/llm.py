"""Streaming LLM client for an LM Studio (OpenAI-compatible) local server.

LM Studio exposes an OpenAI-compatible API at http://localhost:1234/v1, so we use
the official `openai` client and point base_url at it.

Two call shapes:
  - stream_reply(): token stream for the spoken answer (lowest latency, no tools).
  - complete():     one-shot call used by the tool loop; supports native tool
                    calling and returns any tool_calls the model requested.
"""

from __future__ import annotations

import queue
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Iterator

from openai import OpenAI

from config import CONFIG, LLMConfig
from observability import get_logger

log = get_logger("llm")

_STREAM_TIMEOUT_S = 90.0

# Models sometimes echo control tokens from the system prompt (e.g. Gemma + /no_think).
_CONTROL_TOKEN_RE = re.compile(r"\s*/no[-_]think\b", re.I)


def sanitize_llm_output(text: str) -> str:
    return _CONTROL_TOKEN_RE.sub("", text or "").strip()

# Guidance appended to the system prompt when auto-delivery is on. The agent parses
# the first "VOICE:" line out of the stream and feeds it to TTS as a per-reply
# delivery directive; the rest is the spoken reply.
AUTO_INSTRUCT_GUIDE = (
    "Delivery direction: begin every response with a single line that starts with "
    "'VOICE:' followed by a short, comma-separated description of HOW to say this "
    "particular reply - emotion, pace, volume, and any vocal cues that fit the "
    "content (e.g. whispering, laughing, sighing, excited, gentle, deadpan). Then "
    "put the spoken reply on the following line(s). Keep the VOICE line under ~12 "
    "words and never mention it in the spoken text. Example:\n"
    "VOICE: amused, warm, chuckling softly\n"
    "Ha, that's a good one - you got me there."
)


class ToolsUnsupported(Exception):
    """Raised when the server rejects the `tools` parameter (no native calling)."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    raw_arguments: str = "{}"


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMClient:
    def __init__(self, cfg: LLMConfig | None = None):
        self.cfg = cfg or CONFIG.llm
        self.client = OpenAI(base_url=self.cfg.base_url, api_key=self.cfg.api_key)
        self.last_completion_id: str | None = None

    # ----- message assembly -------------------------------------------------

    def base_system_prompt(self, *, include_style_cue: bool = True) -> str:
        """The system prompt plus any always-on directives (style cue, no-think)."""
        system = self.cfg.system_prompt
        if include_style_cue and CONFIG.wants_style_cue():
            system = f"{system}\n\n{AUTO_INSTRUCT_GUIDE}"
        # /no_think is for Qwen3-style templates. Gemma with reasoning_effort=none
        # already skips reasoning and will parrot this token in spoken replies.
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
            # Keep only the most recent exchanges to bound latency.
            keep = self.cfg.history_turns * 2
            messages.extend(history[-keep:])
        messages.append({"role": "user", "content": user_text})
        return messages

    def _extra_body(self) -> dict:
        extra_body: dict = {}
        if self.cfg.disable_thinking:
            # Honored by LM Studio / vLLM for Qwen3-style templates; ignored otherwise.
            extra_body["chat_template_kwargs"] = {"enable_thinking": False}
        effort = (self.cfg.reasoning_effort or "").strip().lower()
        if effort:
            # Honored by reasoning models like Gemma; "none" disables hidden reasoning
            # so the visible reply isn't empty. Sent raw to bypass client validation.
            extra_body["reasoning_effort"] = self.cfg.reasoning_effort
        elif self.cfg.disable_thinking:
            # Many reasoning models return an empty spoken stream unless effort is set.
            extra_body["reasoning_effort"] = "none"
        return extra_body

    @staticmethod
    def _delta_text(delta) -> str:
        if delta is None:
            return ""
        text = getattr(delta, "content", None) or ""
        return text if isinstance(text, str) else ""

    def _create_stream(self, kwargs: dict):
        extra_body = self._extra_body()
        if extra_body:
            kwargs["extra_body"] = extra_body
        try:
            return self.client.chat.completions.create(**kwargs)
        except Exception:
            kwargs.pop("extra_body", None)
            return self.client.chat.completions.create(**kwargs)

    def _iter_stream_chunks(self, response, *, timeout_s: float = _STREAM_TIMEOUT_S) -> Iterator[str]:
        """Yield stream tokens with a wall-clock timeout so a stuck server can't hang voice."""
        out_q: queue.Queue[tuple[str, object]] = queue.Queue()

        def _producer() -> None:
            try:
                for chunk in response:
                    if not chunk.choices:
                        continue
                    chunk_id = getattr(chunk, "id", None)
                    if chunk_id:
                        self.last_completion_id = str(chunk_id)
                    text = self._delta_text(chunk.choices[0].delta)
                    if text:
                        out_q.put(("token", text))
            except Exception as exc:  # noqa: BLE001
                out_q.put(("error", exc))
            finally:
                out_q.put(("done", None))

        threading.Thread(target=_producer, daemon=True, name="llm-stream").start()
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                log.warning("LLM stream timed out after %.0fs", timeout_s)
                break
            try:
                kind, value = out_q.get(timeout=min(remaining, 1.0))
            except queue.Empty:
                continue
            if kind == "token":
                yield str(value)
            elif kind == "error":
                raise value  # type: ignore[misc]
            else:
                break

    def _stream_with_fallback(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
    ) -> Iterator[str]:
        self.last_completion_id = None
        kwargs: dict = dict(
            model=model or self.cfg.model,
            stream=True,
            temperature=self.cfg.temperature,
            top_p=self.cfg.top_p,
            max_tokens=self.cfg.max_tokens,
            messages=messages,
        )
        response = self._create_stream(kwargs)
        yielded = False
        for token in self._iter_stream_chunks(response):
            yielded = True
            yield token
        if yielded:
            return
        log.warning("LLM stream returned no tokens; falling back to complete()")
        text = self.complete(messages, model=model).content
        if text:
            yield text

    # ----- streaming (spoken answer, no tools) ------------------------------

    def stream_reply(self, user_text: str, history: list[dict] | None = None) -> Iterator[str]:
        """Yield content deltas as the model generates them."""
        messages = self._messages(user_text, history)
        yield from self._stream_with_fallback(messages)

    def stream_messages(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
    ) -> Iterator[str]:
        """Stream a reply for a pre-built message list (used after the tool loop)."""
        yield from self._stream_with_fallback(messages, model=model)

    # ----- one-shot completion (tool loop) ----------------------------------

    def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Non-streaming completion. If `tools` is given, request native tool
        calling and surface any tool_calls the model returns."""
        import json as _json

        kwargs: dict = dict(
            model=model or self.cfg.model,
            stream=False,
            temperature=self.cfg.temperature,
            top_p=self.cfg.top_p,
            max_tokens=max_tokens or self.cfg.max_tokens,
            messages=messages,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        extra_body = self._extra_body()
        if extra_body:
            kwargs["extra_body"] = extra_body

        try:
            resp = self.client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            if tools:
                # Server doesn't support tool calling; let the loop fall back.
                raise ToolsUnsupported(str(exc)) from exc
            # Retry once without the extra body (some servers reject it).
            kwargs.pop("extra_body", None)
            resp = self.client.chat.completions.create(**kwargs)

        if not resp.choices:
            log.warning("LLM complete returned no choices")
            return LLMResponse()
        msg = resp.choices[0].message
        content = sanitize_llm_output((msg.content or "").strip())
        if not content:
            finish = getattr(resp.choices[0], "finish_reason", None)
            log.warning("LLM complete returned empty content (finish_reason=%s)", finish)
        out = LLMResponse(content=content)
        for tc in (getattr(msg, "tool_calls", None) or []):
            raw = tc.function.arguments or "{}"
            try:
                parsed = _json.loads(raw)
            except (TypeError, ValueError):
                parsed = {}
            out.tool_calls.append(
                ToolCall(id=tc.id or tc.function.name, name=tc.function.name,
                         arguments=parsed if isinstance(parsed, dict) else {}, raw_arguments=raw)
            )
        return out
