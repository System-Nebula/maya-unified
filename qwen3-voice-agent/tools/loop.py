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

    def run(self, messages: list[dict], emit: Optional[Callable[..., None]] = None) -> ToolLoopResult:
        with span("tool.loop"):
            return self._run(messages, emit)

    def _run(self, messages: list[dict], emit: Optional[Callable[..., None]] = None) -> ToolLoopResult:
        messages = [dict(m) for m in messages]
        trace: list[dict] = []
        json_injected = False

        def _emit(**ev) -> None:
            if emit is not None:
                try:
                    emit(**ev)
                except Exception:  # noqa: BLE001
                    pass

        for rnd in range(self.max_rounds):
            if self._want_native():
                try:
                    resp = self.llm.complete(messages, tools=self.registry.openai_schema())
                except ToolsUnsupported:
                    self._use_native = False
                else:
                    if resp.tool_calls:
                        messages.append(self._assistant_tool_msg(resp))
                        for tc in resp.tool_calls:
                            _emit(type="tool_start", tool=tc.name, args=tc.arguments)
                            result = self.executor.execute(tc.name, tc.arguments)
                            trace.append({"tool": tc.name, "args": tc.arguments, "result": result})
                            _emit(type="tool_end", tool=tc.name, result=result)
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": result,
                            })
                        continue
                    # Some models (e.g. Gemma) emit tool JSON as plain text instead of
                    # structured tool_calls — parse and run it rather than speaking it.
                    call = self._parse_json_call(resp.content or "")
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
                        continue
                    return ToolLoopResult(self._strip_json(resp.content or ""), trace, rnd)

            # JSON-in-prompt fallback.
            if not json_injected:
                messages = self._inject_json_protocol(messages)
                json_injected = True
            resp = self.llm.complete(messages)
            call = self._parse_json_call(resp.content)
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

        # Rounds exhausted: force a final spoken answer with no further tools.
        resp = self.llm.complete(messages)
        return ToolLoopResult(self._strip_json(resp.content), trace, self.max_rounds)

    # ----- helpers ----------------------------------------------------------

    def _want_native(self) -> bool:
        return self._use_native is None or self._use_native is True

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
    def _strip_json(text: str) -> str:
        """Remove any leftover tool-call JSON / code fences from spoken text."""
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
        return cleaned.strip()
