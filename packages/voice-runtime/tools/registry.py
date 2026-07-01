"""Tool registry: a uniform description of every callable the LLM can invoke.

A tool is just a name, a JSON-schema for its arguments, a human description, and
a synchronous Python handler. Built-in memory tools and external MCP tools both
register here, so the agent loop treats them identically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolSpec:
    name: str
    description: str
    # JSON schema (object) describing the tool's arguments.
    parameters: dict
    # Synchronous handler: (args dict) -> JSON-serializable result.
    handler: Callable[[dict], Any]
    # Optional grouping label for the UI (e.g. "memory", "mcp:filesystem").
    group: str = "builtin"


@dataclass
class ToolRegistry:
    _tools: dict[str, ToolSpec] = field(default_factory=dict)

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def register_many(self, specs: list[ToolSpec]) -> None:
        for spec in specs:
            self.register(spec)

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def all(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def openai_schema(self) -> list[dict]:
        """Tool list in OpenAI `tools=[...]` format for native function calling."""
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in self._tools.values()
        ]

    def prompt_descriptions(self) -> str:
        """Human/markdown tool list for the JSON-in-prompt fallback protocol."""
        lines: list[str] = []
        for spec in self._tools.values():
            props = (spec.parameters or {}).get("properties", {})
            arg_bits = []
            for arg, meta in props.items():
                typ = meta.get("type", "any")
                desc = meta.get("description", "")
                arg_bits.append(f"{arg} ({typ}): {desc}".strip())
            args_str = "; ".join(arg_bits) if arg_bits else "no arguments"
            lines.append(f"- {spec.name}: {spec.description} | args: {args_str}")
        return "\n".join(lines)

    def ui_list(self) -> list[dict]:
        """Compact list for the web UI Tools page."""
        return [
            {"name": s.name, "group": s.group, "description": s.description}
            for s in self._tools.values()
        ]
