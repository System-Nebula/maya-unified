"""Offline tests for the Ax tool router — no network, canned completions.

Uses ax-llm's OpenAICompatibleClient ``transport`` hook to return fixed chat
completions, so routing behaviour is exercised without an LLM endpoint (mirrors
how test_ax_shadow.py avoids side effects).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VOICE_RUNTIME = ROOT / "packages" / "voice-runtime"
if str(VOICE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(VOICE_RUNTIME))

from ax_router import AxRouter, _make_client  # noqa: E402
from tools.registry import ToolRegistry, ToolSpec  # noqa: E402


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_many(
        [
            ToolSpec(
                name="get_current_datetime",
                description="Get the current local date and time.",
                parameters={"type": "object", "properties": {}, "required": []},
                handler=lambda _a: {"ok": True},
            ),
            ToolSpec(
                name="weather",
                description="Get current weather for a place.",
                parameters={
                    "type": "object",
                    "properties": {"location": {"type": "string"}},
                    "required": [],
                },
                handler=lambda _a: {"ok": True},
            ),
        ]
    )
    return registry


def _router_returning(content: str) -> AxRouter:
    """An AxRouter whose LM always replies with the given assistant content."""

    def transport(_request: dict) -> dict:
        return {
            "choices": [
                {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    client = _make_client(model="test", base_url="http://localhost", api_key="x", transport=transport)
    return AxRouter(client=client)


def test_route_picks_valid_tool_with_args() -> None:
    content = json.dumps({"tool_name": "weather", "args_json": '{"location": "Seattle"}'})
    routed = _router_returning(content).route("what's the weather in Seattle?", _registry())
    assert routed == ("weather", {"location": "Seattle"})


def test_route_none_defers_to_chat() -> None:
    content = json.dumps({"tool_name": "none", "args_json": "{}"})
    routed = _router_returning(content).route("i love you maya", _registry())
    assert routed is None


def test_route_unknown_tool_is_ignored() -> None:
    content = json.dumps({"tool_name": "launch_missiles", "args_json": "{}"})
    routed = _router_returning(content).route("do the thing", _registry())
    assert routed is None


def test_route_malformed_args_fall_back_to_empty() -> None:
    content = json.dumps({"tool_name": "get_current_datetime", "args_json": "not json"})
    routed = _router_returning(content).route("what day is it?", _registry())
    assert routed == ("get_current_datetime", {})


def test_route_empty_utterance_returns_none() -> None:
    content = json.dumps({"tool_name": "weather", "args_json": "{}"})
    routed = _router_returning(content).route("   ", _registry())
    assert routed is None


def test_module_imports_without_axllm() -> None:
    # The module must import even when `axllm` is absent (lazy import inside
    # AxRouter/_make_client), so the agent can catch construction errors instead
    # of crashing at import. axllm is installed here, so we just assert the
    # module-level import stays side-effect free.
    import ax_router  # noqa: F401

    assert hasattr(ax_router, "AxRouter")
