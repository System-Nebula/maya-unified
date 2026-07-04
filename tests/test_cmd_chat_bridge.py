"""Tests for dashboard chat cmd bridge + SSE payloads."""

from __future__ import annotations

import asyncio
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from services.cmd.chat_bridge import (
    _broadcast_cmd_turn,
    _ensure_cmd_result,
    _format_cmd_exception,
    _resolve_cmd_error_text,
    _run_long_cmd_async,
    try_dispatch_chat_cmd,
)
from services.cmd.models import CmdContext, CmdResult, CmdSurface, ParsedCmd


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

    with _patch_voice_hub(mock_hub), patch("services.cmd.chat_bridge._schedule_persist_cmd_turns"):
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

    with _patch_voice_hub(mock_hub), patch("services.cmd.chat_bridge._schedule_persist_cmd_turns"):
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

    with _patch_voice_hub(mock_hub), patch("services.cmd.chat_bridge._schedule_persist_cmd_turns"):
        out = _broadcast_cmd_turn(text="/imagine alley", reply=reply, operator_id="op-1")

    error_events = [b for b in broadcasts if b.get("type") == "error"]
    assert len(error_events) == 1
    assert error_events[0]["trace_id"] == "abc123trace"
    assert error_events[0]["corr_id"].startswith("c_")
    assert out["trace_id"] == "abc123trace"
    assert out["corr_id"] == error_events[0]["corr_id"]


def test_persist_cmd_turns_appends_assistant_on_success() -> None:
    from services.cmd.chat_bridge import _persist_cmd_turns

    reply = CmdResult(ok=True, text="Image ready.\nJob: job-1")
    mock_append = MagicMock()
    op_id = "00000000-0000-0000-0000-000000000001"

    with patch("services.operator_voice.context.append_turn", mock_append):
        _persist_cmd_turns(
            operator_id=op_id,
            text="/imagine dog",
            reply=reply,
            corr_id="c_test123",
            reply_message_id="m_test123",
            skip_user=True,
        )

    mock_append.assert_called_once_with(
        op_id,
        "assistant",
        "Image ready.\nJob: job-1",
        message_id="m_test123",
        corr_id="c_test123",
    )


def test_try_dispatch_imagine_returns_pending_immediately() -> None:
    """Long /imagine returns HTTP ack only; SSE carries thinking + later done/error.

    Manual smoke (after gateway restart + dashboard hard-refresh):
    1. Send `/imagine A DOG WEARING A PARTY HAT !`
    2. Within ~1s: operator + maya ack share the same corr_id; no `chat N ms` on ack
    3. After ComfyUI finishes (~30–110s): ack upgrades to image + idle status
    """
    broadcasts: list[dict] = []
    mock_hub = MagicMock()
    mock_hub.broadcast.side_effect = lambda payload, **_: broadcasts.append(payload)

    scheduled: list = []

    def _capture_schedule(coro) -> None:
        scheduled.append(coro)

    with _patch_voice_hub(mock_hub):
        with patch("services.async_bridge.schedule_coro", side_effect=_capture_schedule):
            with patch("services.cmd.chat_bridge.parse_cmd_input") as mock_parse:
                mock_parse.return_value = ParsedCmd(
                    cmd_id="imagine",
                    name="imagine",
                    raw_args="a dog",
                    args={"prompt": "a dog"},
                )
                out = try_dispatch_chat_cmd("/imagine a dog", operator_id="op-1")

    assert out["ok"] is True
    assert out["pending"] is True
    assert out["cmd_phase"] == "ack"
    assert "Generating image" in out["text"]
    assert out["corr_id"].startswith("c_")
    ack_events = [
        b for b in broadcasts if b.get("type") == "ai" and b.get("cmd_phase") == "ack"
    ]
    assert len(ack_events) == 0
    thinking_events = [
        b for b in broadcasts if b.get("type") == "status" and b.get("value") == "thinking"
    ]
    assert len(thinking_events) == 1
    assert thinking_events[0]["corr_id"] == out["corr_id"]
    assert len(scheduled) == 1
    scheduled[0].close()


def test_format_cmd_exception_timeout_is_not_empty() -> None:
    msg = _format_cmd_exception(TimeoutError(), cmd_id="imagine", timeout_sec=300.0)
    assert "imagine timed out after 300s" in msg
    assert msg.strip()


def test_resolve_cmd_error_text_never_empty() -> None:
    assert _resolve_cmd_error_text(CmdResult(ok=False), cmd_id="imagine") == (
        "imagine failed with no details"
    )
    assert _resolve_cmd_error_text(
        CmdResult(ok=False, error=""),
        cmd_id="blend",
    ) == "blend failed with no details"


def test_format_cmd_exception_cancelled() -> None:
    msg = _format_cmd_exception(asyncio.CancelledError(), cmd_id="imagine", timeout_sec=300.0)
    assert "imagine cancelled" in msg
    assert "gateway may have reloaded" in msg


def test_ensure_cmd_result_fills_empty_error() -> None:
    out = _ensure_cmd_result(CmdResult(ok=False, error=""), cmd_id="imagine")
    assert out.ok is False
    assert "no details" in (out.error or "")
    assert "gateway logs" in (out.error or "")


def test_ensure_cmd_result_invalid_type() -> None:
    out = _ensure_cmd_result(None, cmd_id="blend")
    assert out.ok is False
    assert "invalid result" in (out.error or "")


def test_broadcast_cmd_turn_never_empty_error() -> None:
    reply = CmdResult(ok=False, error="")
    broadcasts: list[dict] = []

    mock_hub = MagicMock()
    mock_hub.broadcast.side_effect = lambda payload, **_: broadcasts.append(payload)

    with _patch_voice_hub(mock_hub), patch("services.cmd.chat_bridge._schedule_persist_cmd_turns"):
        _broadcast_cmd_turn(
            text="/imagine dog",
            reply=reply,
            operator_id=None,
            cmd_id="imagine",
        )

    error_events = [b for b in broadcasts if b.get("type") == "error"]
    assert len(error_events) == 1
    assert "no details" in error_events[0]["text"]
    assert "gateway logs" in error_events[0]["text"]


@pytest.mark.asyncio
async def test_background_cancelled_broadcasts_reload_error() -> None:
    broadcasts: list[dict] = []
    mock_hub = MagicMock()
    mock_hub.broadcast.side_effect = lambda payload, **_: broadcasts.append(payload)

    parsed = ParsedCmd(cmd_id="imagine", name="imagine", raw_args="dog", args={"prompt": "dog"})
    ctx = CmdContext(operator_id="op-1", surface=CmdSurface.DASHBOARD, raw_text="/imagine dog")

    with _patch_voice_hub(mock_hub), patch("services.cmd.chat_bridge._schedule_persist_cmd_turns"):
        with patch(
            "services.cmd.chat_bridge.dispatch_cmd_async",
            side_effect=asyncio.CancelledError,
        ):
            await _run_long_cmd_async(
                parsed=parsed,
                ctx=ctx,
                text="/imagine dog",
                corr_id="c_cancel_test",
                operator_id="op-1",
            )

    error_events = [b for b in broadcasts if b.get("type") == "error"]
    assert len(error_events) == 1
    assert "cancelled" in error_events[0]["text"]
    assert "gateway may have reloaded" in error_events[0]["text"]


def test_broadcast_cmd_turn_sends_sse_before_persist() -> None:
    broadcasts: list[dict] = []
    persist_called = False

    mock_hub = MagicMock()
    mock_hub.broadcast.side_effect = lambda payload, **_: broadcasts.append(payload)

    def _mark_persist(**_) -> None:
        nonlocal persist_called
        persist_called = True

    with _patch_voice_hub(mock_hub):
        with patch("services.cmd.chat_bridge._schedule_persist_cmd_turns", side_effect=_mark_persist):
            _broadcast_cmd_turn(
                text="/imagine dog",
                reply=CmdResult(ok=False, error="weights missing"),
                operator_id="op-1",
                cmd_id="imagine",
            )

    error_events = [b for b in broadcasts if b.get("type") == "error"]
    assert len(error_events) == 1
    assert len(broadcasts) >= 2
    assert persist_called


@pytest.mark.asyncio
async def test_background_timeout_error_is_not_empty() -> None:
    broadcasts: list[dict] = []
    mock_hub = MagicMock()
    mock_hub.broadcast.side_effect = lambda payload, **_: broadcasts.append(payload)

    parsed = ParsedCmd(cmd_id="imagine", name="imagine", raw_args="dog", args={"prompt": "dog"})
    ctx = CmdContext(operator_id="op-1", surface=CmdSurface.DASHBOARD, raw_text="/imagine dog")

    with _patch_voice_hub(mock_hub), patch("services.cmd.chat_bridge._schedule_persist_cmd_turns"):
        with patch(
            "services.cmd.chat_bridge.dispatch_cmd_async",
            side_effect=TimeoutError,
        ):
            await _run_long_cmd_async(
                parsed=parsed,
                ctx=ctx,
                text="/imagine dog",
                corr_id="c_timeout_test",
                operator_id="op-1",
            )

    error_events = [b for b in broadcasts if b.get("type") == "error"]
    assert len(error_events) == 1
    assert "timed out after 300s" in error_events[0]["text"]
