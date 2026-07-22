from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VOICE_RUNTIME = ROOT / "packages" / "voice-runtime"
if str(VOICE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(VOICE_RUNTIME))

from services.llm.ax_shadow import AxShadowRecorder  # noqa: E402
from tools.registry import ToolRegistry, ToolSpec  # noqa: E402


def test_shadow_handler_records_without_invoking_real_handler() -> None:
    invoked = False

    def real_handler(_args):
        nonlocal invoked
        invoked = True
        raise AssertionError("shadow adapter reached production handler")

    spec = ToolSpec(
        name="dangerous_write",
        description="A deliberately side-effecting test tool.",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        handler=real_handler,
        group="danger",
    )
    recorder = AxShadowRecorder()
    result = recorder.handler_for(spec)({"value": "hello"})
    assert not invoked
    assert result["shadow"] is True
    assert recorder.calls[0].tool_name == "dangerous_write"
    assert recorder.calls[0].arguments == {"value": "hello"}


def test_shadow_handler_rejects_invalid_arguments_without_recording() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="needs_value",
            description="Requires a value.",
            parameters={
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
            },
            handler=lambda _args: None,
        )
    )
    spec = registry.get("needs_value")
    assert spec is not None
    recorder = AxShadowRecorder()
    try:
        recorder.handler_for(spec)({})
    except Exception:
        pass
    else:
        raise AssertionError("invalid shadow arguments were accepted")
    assert recorder.calls == []
