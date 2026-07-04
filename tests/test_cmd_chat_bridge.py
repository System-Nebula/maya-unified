"""Tests for dashboard chat cmd bridge + SSE payloads."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

from services.cmd.chat_bridge import _broadcast_cmd_turn
from services.cmd.models import CmdResult


def _patch_voice_hub(mock_hub):
    mock_mod = ModuleType("services.voice.hub")
    mock_mod.hub = mock_hub
    return patch.dict(sys.modules, {"services.voice.hub": mock_mod})


def test_broadcast_cmd_turn_includes_artifacts_in_ai_event() -> None:
    reply = CmdResult(
        ok=True,
        text="Image ready.\nJob: job-1",
        artifacts=[{"type": "image", "url": "https://example.com/out.png", "job_id": "job-1"}],
    )
    broadcasts: list[dict] = []

    mock_hub = MagicMock()
    mock_hub.broadcast.side_effect = lambda payload, **_: broadcasts.append(payload)

    with _patch_voice_hub(mock_hub):
        out = _broadcast_cmd_turn(text="/imagine alley", reply=reply, operator_id="op-1")

    assert out["ok"] is True
    assert out["artifacts"][0]["url"] == "https://example.com/out.png"
    ai_events = [b for b in broadcasts if b.get("type") == "ai"]
    assert len(ai_events) == 1
    assert ai_events[0]["mode"] == "cmd"
    assert ai_events[0]["artifacts"][0]["job_id"] == "job-1"


def test_broadcast_cmd_turn_marks_cmd_errors() -> None:
    reply = CmdResult(ok=False, error="missing required parameter: prompt")
    broadcasts: list[dict] = []

    mock_hub = MagicMock()
    mock_hub.broadcast.side_effect = lambda payload, **_: broadcasts.append(payload)

    with _patch_voice_hub(mock_hub):
        out = _broadcast_cmd_turn(text="/imagine", reply=reply, operator_id=None)

    error_events = [b for b in broadcasts if b.get("type") == "error"]
    assert len(error_events) == 1
    assert error_events[0]["mode"] == "cmd"
    assert "prompt" in error_events[0]["text"]
    assert error_events[0]["corr_id"].startswith("c_")
    assert out["corr_id"] == error_events[0]["corr_id"]


def test_broadcast_cmd_turn_error_includes_trace_and_job_ids() -> None:
    reply = CmdResult(
        ok=False,
        error="ComfyUI is not reachable at http://localhost:3000. Cannot connect.",
        trace_id="abc123trace",
    )
    broadcasts: list[dict] = []

    mock_hub = MagicMock()
    mock_hub.broadcast.side_effect = lambda payload, **_: broadcasts.append(payload)

    with _patch_voice_hub(mock_hub):
        out = _broadcast_cmd_turn(text="/imagine alley", reply=reply, operator_id="op-1")

    error_events = [b for b in broadcasts if b.get("type") == "error"]
    assert len(error_events) == 1
    assert error_events[0]["trace_id"] == "abc123trace"
    assert error_events[0]["corr_id"].startswith("c_")
    assert out["trace_id"] == "abc123trace"
    assert out["corr_id"] == error_events[0]["corr_id"]
