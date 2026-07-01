"""Tool / function-calling runtime for the voice agent.

The agent can call tools (built-in memory, session search, and external MCP
servers) before it speaks. See `registry` for the tool abstraction, `executor`
for sandboxed execution, and `loop` for the LLM<->tool agent loop.
"""

from .registry import ToolSpec, ToolRegistry
from .executor import ToolExecutor
from .loop import ToolLoop, ToolLoopResult

__all__ = [
    "ToolSpec",
    "ToolRegistry",
    "ToolExecutor",
    "ToolLoop",
    "ToolLoopResult",
]
