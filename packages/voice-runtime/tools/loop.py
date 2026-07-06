"""The LLM <-> tool agent loop.

Runs up to `max_rounds` tool round-trips, then returns the final text the agent
should speak. Supports two protocols:

  - native: OpenAI `tools` + `tool_calls` (tool-capable models / LM Studio).
  - json:   the model emits a JSON object {"tool": ..., "args": {...}} which we
            parse out, run, and feed back. Used for models without tool calling.

In "auto" mode we try native first and fall back to json for the session if the
server rejects the `tools` parameter.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from llm import LLMClient, ToolsUnsupported
from observability import get_logger, span

from .executor import ToolExecutor
from .registry import ToolRegistry

log = get_logger("tools.loop")


def _iter_json_objects(text: str):
    """Yield (start, end, substring) for each top-level balanced {...} block."""
    depth = 0
    start = -1
    in_str = False
    escape = False
    for i, ch in enumerate(text):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    yield start, i + 1, text[start:i + 1]


@dataclass
class ToolLoopResult:
    final_text: str
    trace: list[dict] = field(default_factory=list)
    rounds: int = 0


class ToolLoop:
    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        executor: ToolExecutor,
        max_rounds: int = 3,
        mode: str = "auto",
    ):
        self.llm = llm
        self.registry = registry
        self.executor = executor
        self.max_rounds = max(1, max_rounds)
        self.mode = (mode or "auto").lower()
        # None = undecided (auto); set once we learn what the server supports.
        self._use_native: Optional[bool] = {"native": True, "json": False}.get(self.mode)

    def run(
        self,
        messages: list[dict],
        emit: Optional[Callable[..., None]] = None,
        *,
        max_rounds: int | None = None,
    ) -> ToolLoopResult:
        with span("tool.loop"):
            return self._run(messages, emit, max_rounds=max_rounds)

    def _run(
        self,
        messages: list[dict],
        emit: Optional[Callable[..., None]] = None,
        *,
        max_rounds: int | None = None,
    ) -> ToolLoopResult:
        messages = [dict(m) for m in messages]
        trace: list[dict] = []
        json_injected = False
        rounds = max(1, max_rounds if max_rounds is not None else self.max_rounds)

        def _emit(**ev) -> None:
            if emit is not None:
                try:
                    emit(**ev)
                except Exception:  # noqa: BLE001
                    pass

        for rnd in range(rounds):
            if self._want_native():
                try:
                    resp = self.llm.complete(messages, tools=self.registry.openai_schema())
                except ToolsUnsupported:
                    self._use_native = False
                else:
                    if resp.tool_calls:
                        messages.append(self._assistant_tool_msg(resp))
                        for tc in resp.tool_calls:
                            dup = self._duplicate_imagine_result(tc.name, trace)
                            _emit(type="tool_start", tool=tc.name, args=tc.arguments)
                            if dup is not None:
                                result = dup
                            else:
                                result = self.executor.execute(tc.name, tc.arguments)
                            trace.append({"tool": tc.name, "args": tc.arguments, "result": result})
                            _emit(type="tool_end", tool=tc.name, result=result)
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": result,
                            })
                        remark = self._maybe_finish_imagine_remark(messages, trace, emit)
                        if remark is not None:
                            return ToolLoopResult(remark, trace, rnd)
                        continue
                    # Some models emit tool syntax as plain text instead of structured
                    # tool_calls — parse and run it rather than speaking it.
                    call = self._parse_json_call(resp.content or "")
                    if call is None:
                        call = self._parse_text_call(resp.content or "")
                    if call is not None and self.registry.get(call.get("tool", "")):
                        name = call["tool"]
                        args = call.get("args", {}) if isinstance(call.get("args"), dict) else {}
                        _emit(type="tool_start", tool=name, args=args)
                        result = self.executor.execute(name, args)
                        trace.append({"tool": name, "args": args, "result": result})
                        _emit(type="tool_end", tool=name, result=result)
                        messages.append({"role": "assistant", "content": resp.content})
                        messages.append({
                            "role": "user",
                            "content": (
                                f"Tool result for {name}:\n{result}\n\n"
                                "Use this to answer now. Reply in plain text with no JSON."
                            ),
                        })
                        remark = self._maybe_finish_imagine_remark(messages, trace, emit)
                        if remark is not None:
                            return ToolLoopResult(remark, trace, rnd)
                        continue
                    return ToolLoopResult(self._strip_json(resp.content or ""), trace, rnd)

            # JSON-in-prompt fallback.
            if not json_injected:
                messages = self._inject_json_protocol(messages)
                json_injected = True
            resp = self.llm.complete(messages)
            call = self._parse_json_call(resp.content)
            if call is None:
                call = self._parse_text_call(resp.content or "")
            if call is None:
                return ToolLoopResult(self._strip_json(resp.content), trace, rnd)
            name = call.get("tool", "")
            args = call.get("args", {}) if isinstance(call.get("args"), dict) else {}
            _emit(type="tool_start", tool=name, args=args)
            result = self.executor.execute(name, args)
            trace.append({"tool": name, "args": args, "result": result})
            _emit(type="tool_end", tool=name, result=result)
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({
                "role": "user",
                "content": (
                    f"Tool result for {name}:\n{result}\n\n"
                    "Use this to answer now. If you have what you need, reply normally "
                    "with no JSON."
                ),
            })
            remark = self._maybe_finish_imagine_remark(messages, trace, emit)
            if remark is not None:
                return ToolLoopResult(remark, trace, rnd)

        # Rounds exhausted: force a final spoken answer with no further tools.
        resp = self.llm.complete(messages)
        return ToolLoopResult(self._strip_json(resp.content), trace, rounds)

    # ----- helpers ----------------------------------------------------------

    def _want_native(self) -> bool:
        return self._use_native is None or self._use_native is True

    @staticmethod
    def _duplicate_imagine_result(tool_name: str, trace: list[dict]) -> str | None:
        """Reuse the first imagine_generate result when the model emits duplicates in one round."""
        if tool_name != "imagine_generate":
            return None
        for entry in trace:
            if entry.get("tool") == "imagine_generate":
                return str(entry.get("result") or "")
        return None

    def _maybe_finish_imagine_remark(
        self,
        messages: list[dict],
        trace: list[dict],
        emit: Optional[Callable[..., None]],
    ) -> str | None:
        if not trace:
            return None
        last = trace[-1]
        if last.get("tool") != "imagine_generate":
            return None
        result = str(last.get("result") or "")
        try:
            from services.imagine.remark import (
                finish_imagine_remark_with_fallback,
                parse_imagine_tool_result,
            )
            from services.settings.store import load_effective_settings
            from services.imagine.tool_context import get_imagine_tool_context

            if not parse_imagine_tool_result(result):
                return None
            ctx = get_imagine_tool_context()
            settings = load_effective_settings(ctx.get("operator_id"))
            system = self.llm.base_system_prompt()
            return finish_imagine_remark_with_fallback(
                self.llm,
                messages,
                result,
                system_prompt=system,
                settings=settings,
                emit=emit,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("imagine_remark_finish_failed: %s", exc)
            from services.imagine.remark import _IMAGINE_REMARK_FALLBACK

            return _IMAGINE_REMARK_FALLBACK

    @staticmethod
    def _assistant_tool_msg(resp) -> dict:
        return {
            "role": "assistant",
            "content": resp.content or None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.raw_arguments},
                }
                for tc in resp.tool_calls
            ],
        }

    def _inject_json_protocol(self, messages: list[dict]) -> list[dict]:
        guide = (
            "You can use tools. To call one, reply with ONLY a single JSON object "
            "on its own line and nothing else:\n"
            '{"tool": "<tool_name>", "args": {<arguments>}}\n'
            "After you receive the tool result, answer the user normally in plain "
            "text with no JSON. Only call a tool when you actually need it; "
            "otherwise just answer directly.\n\n"
            "Available tools:\n" + self.registry.prompt_descriptions()
        )
        out = list(messages)
        # Insert right after the main system message so it stays near instructions.
        insert_at = 1 if out and out[0].get("role") == "system" else 0
        out.insert(insert_at, {"role": "system", "content": guide})
        return out

    @staticmethod
    def _parse_json_call(text: str) -> Optional[dict]:
        if not text or '"tool"' not in text:
            return None
        for _start, _end, blob in _iter_json_objects(text):
            try:
                obj = json.loads(blob)
            except (TypeError, ValueError):
                continue
            if isinstance(obj, dict) and isinstance(obj.get("tool"), str):
                return obj
        return None

    @staticmethod
    def _parse_text_call(text: str) -> Optional[dict]:
        from tools.text_calls import parse_text_tool_calls

        calls = parse_text_tool_calls(text or "")
        if not calls:
            return None
        name, args = calls[0]
        return {"tool": name, "args": args if isinstance(args, dict) else {}}

    @staticmethod
    def _strip_json(text: str) -> str:
        """Remove any leftover tool-call JSON / code fences from spoken text."""
        from memory.character_card import strip_llm_artifacts

        if not text:
            return ""
        cleaned = text
        for _start, _end, blob in reversed(list(_iter_json_objects(text))):
            try:
                obj = json.loads(blob)
            except (TypeError, ValueError):
                continue
            if isinstance(obj, dict) and "tool" in obj:
                cleaned = cleaned[:_start] + cleaned[_end:]
        cleaned = re.sub(r"```(?:json)?\s*```", "", cleaned)
        return strip_llm_artifacts(cleaned)
