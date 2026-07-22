"""Side-effect-free Ax adapters over Maya's canonical tool registry."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from services.llm.programs import ProposedToolCall


class ShadowToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    shadow: bool = True
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    note: str = "Recorded for evaluation; production handler was not executed."


class AxShadowRecorder:
    """Build callbacks that can record calls but cannot reach ToolExecutor."""

    def __init__(self) -> None:
        self._calls: list[ProposedToolCall] = []
        self._lock = threading.Lock()

    @property
    def calls(self) -> list[ProposedToolCall]:
        with self._lock:
            return list(self._calls)

    def handler_for(self, spec: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
        def handler(raw_arguments: dict[str, Any]) -> dict[str, Any]:
            validated = spec.validate_arguments(raw_arguments)
            arguments = validated.model_dump(mode="json", exclude_unset=True)
            with self._lock:
                call = ProposedToolCall(
                    tool_name=spec.name,
                    arguments=arguments,
                    group=spec.group,
                    sequence=len(self._calls) + 1,
                )
                self._calls.append(call)
            return ShadowToolResult(
                tool_name=spec.name,
                arguments=arguments,
            ).model_dump(mode="json")

        return handler


def build_ax_shadow_tools(registry: Any, recorder: AxShadowRecorder) -> list[Any]:
    """Convert every registry entry to an Ax Tool without its real handler."""
    try:
        from axllm import Tool
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Ax support requires `uv sync --extra ax`") from exc

    return [
        Tool(
            name=spec.name,
            description=spec.description,
            parameters=spec.input_model.model_json_schema(),
            handler=recorder.handler_for(spec),
        )
        for spec in registry.all()
    ]

