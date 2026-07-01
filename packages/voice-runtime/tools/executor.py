"""Tool executor: run a tool handler with a timeout and normalized errors.

Handlers may block (MCP IO, embeddings), so each call runs on a worker thread we
can abandon if it overruns. Results are coerced to a string for the LLM.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from observability import get_logger, record_tool, span

from .registry import ToolRegistry, ToolSpec

log = get_logger("tools.executor")


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, timeout: float = 30.0):
        self.registry = registry
        self.timeout = timeout

    def execute(self, name: str, args: dict) -> str:
        spec = self.registry.get(name)
        if spec is None:
            record_tool(name, error=True)
            return self._err(f"unknown tool '{name}'")
        if not isinstance(args, dict):
            args = {}
        with span("tool.execute", tool=name):
            log.info("tool start name=%s args=%s", name, args)
            result = self._run_with_timeout(spec, args)
            is_error = '"error"' in result[:80]
            record_tool(name, error=is_error)
            log.info("tool end name=%s error=%s", name, is_error)
            return result

    def _run_with_timeout(self, spec: ToolSpec, args: dict) -> str:
        result_box: dict[str, Any] = {}

        def worker() -> None:
            try:
                result_box["value"] = spec.handler(args)
            except Exception as exc:  # noqa: BLE001 - surface tool errors to the model
                result_box["error"] = str(exc)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout=self.timeout)

        if thread.is_alive():
            return self._err(f"tool '{spec.name}' timed out after {self.timeout:.0f}s")
        if "error" in result_box:
            return self._err(result_box["error"])
        return self._stringify(result_box.get("value"))

    @staticmethod
    def _stringify(value: Any) -> str:
        if value is None:
            return "ok"
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _err(message: str) -> str:
        return json.dumps({"error": message}, ensure_ascii=False)
