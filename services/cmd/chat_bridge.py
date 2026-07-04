"""Bridge cmd dispatch into dashboard chat + SSE."""

from __future__ import annotations

import asyncio

import structlog

from services.cmd.bootstrap import ensure_cmds_registered
from services.cmd.dispatcher import dispatch_cmd_async
from services.cmd.models import CmdContext, CmdResult, CmdSurface, ParsedCmd
from services.cmd.parser import is_cmd_input, parse_cmd_input
from services.cmd.registry import registry
from services.ids import new_corr_id, new_message_id

log = structlog.get_logger("maya-unified.cmd")

_LONG_RUNNING_CMDS = frozenset({"imagine", "blend"})
_LONG_CMD_TIMEOUT_SEC = 300.0
_CMD_ACK_TEXT = {
    "imagine": (
        "Generating image… Z-Image Turbo may take up to a minute while models load."
    ),
    "blend": "Running Blender…",
}


def _format_cmd_exception(exc: BaseException, *, cmd_id: str, timeout_sec: float) -> str:
    if isinstance(exc, (asyncio.CancelledError, TimeoutError)):
        if isinstance(exc, asyncio.CancelledError):
            return f"{cmd_id} cancelled (gateway may have reloaded)"
        return (
            f"{cmd_id} timed out after {int(timeout_sec)}s waiting for the gateway event loop"
        )
    msg = str(exc).strip()
    if msg:
        return msg
    return f"{cmd_id} failed: {type(exc).__name__}"


def _ensure_cmd_result(result: CmdResult | None, *, cmd_id: str) -> CmdResult:
    if not isinstance(result, CmdResult):
        return CmdResult(ok=False, error=f"{cmd_id} returned invalid result")
    if not result.ok and not (result.error or result.text or "").strip():
        return result.model_copy(
            update={
                "error": (
                    f"{cmd_id} failed (no details — check gateway logs for corr_id / trace_id)"
                )
            }
        )
    return result


def _resolve_cmd_error_text(reply: CmdResult, *, cmd_id: str | None = None) -> str:
    label = cmd_id or "command"
    err = (reply.error or reply.text or "").strip()
    if err:
        return err
    return f"{label} failed with no details"


def _chat_event(payload: dict, *, corr_id: str, message_id: str | None = None) -> dict:
    out = dict(payload)
    out["corr_id"] = corr_id
    if message_id:
        out["message_id"] = message_id
    return out


def _persist_cmd_turns(
    *,
    operator_id: str | None,
    text: str,
    reply: CmdResult,
    corr_id: str,
    reply_message_id: str,
    skip_user: bool,
) -> None:
    if not operator_id:
        return
    from services.operator_voice import context as op_ctx

    try:
        if not skip_user and text.strip():
            op_ctx.append_turn(operator_id, "user", text, corr_id=corr_id)
        if reply.ok:
            body = (reply.text or "").strip()
            if body:
                op_ctx.append_turn(
                    operator_id,
                    "assistant",
                    body,
                    message_id=reply_message_id,
                    corr_id=corr_id,
                )
        else:
            err = _resolve_cmd_error_text(reply)
            op_ctx.append_turn(operator_id, "system", err, corr_id=corr_id)
    except Exception:
        log.exception("cmd_persist_failed", corr_id=corr_id, operator_id=operator_id)


def _schedule_persist_cmd_turns(
    *,
    operator_id: str | None,
    text: str,
    reply: CmdResult,
    corr_id: str,
    reply_message_id: str,
    skip_user: bool,
) -> None:
    """Fire-and-forget conversation persist — must not block SSE delivery."""
    if not operator_id:
        return
    from services.async_bridge import schedule_coro

    async def _persist_async() -> None:
        await asyncio.to_thread(
            _persist_cmd_turns,
            operator_id=operator_id,
            text=text,
            reply=reply,
            corr_id=corr_id,
            reply_message_id=reply_message_id,
            skip_user=skip_user,
        )

    schedule_coro(_persist_async())


def _broadcast_cmd_turn(
    *,
    text: str,
    reply: CmdResult,
    operator_id: str | None,
    corr_id: str | None = None,
    skip_user: bool = False,
    cmd_id: str | None = None,
) -> dict:
    from services.voice.hub import hub

    reply = _ensure_cmd_result(reply, cmd_id=cmd_id or "command")
    corr_id = corr_id or new_corr_id()
    user_message_id = new_message_id()
    reply_message_id = new_message_id()
    if not skip_user:
        hub.broadcast(
            _chat_event({"type": "user", "text": text}, corr_id=corr_id, message_id=user_message_id),
            operator_id=operator_id,
        )
    if reply.ok:
        ai_payload: dict = {
            "type": "ai",
            "text": reply.text,
            "mode": "cmd",
            "cmd_phase": "done",
        }
        if reply.artifacts:
            ai_payload["artifacts"] = reply.artifacts
        hub.broadcast(
            _chat_event(
                ai_payload,
                corr_id=corr_id,
                message_id=reply_message_id,
            ),
            operator_id=operator_id,
        )
    else:
        err_text = _resolve_cmd_error_text(reply, cmd_id=cmd_id)
        err_payload: dict = {
            "type": "error",
            "text": err_text,
            "mode": "cmd",
        }
        if reply.trace_id:
            err_payload["trace_id"] = reply.trace_id
        if reply.job_id:
            err_payload["job_id"] = reply.job_id
        hub.broadcast(
            _chat_event(err_payload, corr_id=corr_id),
            operator_id=operator_id,
        )
        log.error(
            "cmd_dispatch_failed",
            corr_id=corr_id,
            trace_id=reply.trace_id,
            job_id=reply.job_id,
            error=err_text,
        )
    hub.broadcast(_chat_event({"type": "status", "value": "idle"}, corr_id=corr_id), operator_id=operator_id)
    _schedule_persist_cmd_turns(
        operator_id=operator_id,
        text=text,
        reply=reply,
        corr_id=corr_id,
        reply_message_id=reply_message_id,
        skip_user=skip_user,
    )
    out = reply.to_chat_response()
    if not reply.ok:
        out["error"] = _resolve_cmd_error_text(reply, cmd_id=cmd_id)
    out["corr_id"] = corr_id
    if reply.trace_id:
        out["trace_id"] = reply.trace_id
    if reply.job_id:
        out["job_id"] = reply.job_id
    return out


def _immediate_pending_response(*, corr_id: str, cmd_id: str) -> dict:
    ack = _CMD_ACK_TEXT.get(cmd_id, "Working on it…")
    return {
        "ok": True,
        "mode": "cmd",
        "cmd_phase": "ack",
        "pending": True,
        "text": ack,
        "corr_id": corr_id,
    }


async def _run_long_cmd_async(
    *,
    parsed: ParsedCmd,
    ctx: CmdContext,
    text: str,
    corr_id: str,
    operator_id: str | None,
) -> None:
    result: CmdResult | None = None
    broadcasted = False
    try:
        result = await dispatch_cmd_async(parsed, ctx)
    except asyncio.CancelledError:
        result = CmdResult(
            ok=False,
            error=_format_cmd_exception(
                asyncio.CancelledError(),
                cmd_id=parsed.cmd_id,
                timeout_sec=_LONG_CMD_TIMEOUT_SEC,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("long_cmd_background_failed", cmd_id=parsed.cmd_id, corr_id=corr_id)
        result = CmdResult(
            ok=False,
            error=_format_cmd_exception(
                exc,
                cmd_id=parsed.cmd_id,
                timeout_sec=_LONG_CMD_TIMEOUT_SEC,
            ),
        )
    result = _ensure_cmd_result(result, cmd_id=parsed.cmd_id)
    try:
        _broadcast_cmd_turn(
            text=text,
            reply=result,
            operator_id=operator_id,
            corr_id=corr_id,
            skip_user=True,
            cmd_id=parsed.cmd_id,
        )
        broadcasted = True
    except Exception:
        log.exception("long_cmd_broadcast_failed", corr_id=corr_id, cmd_id=parsed.cmd_id)
    if not broadcasted:
        try:
            _broadcast_cmd_turn(
                text=text,
                reply=result,
                operator_id=operator_id,
                corr_id=corr_id,
                skip_user=True,
                cmd_id=parsed.cmd_id,
            )
        except Exception:
            log.exception("long_cmd_broadcast_retry_failed", corr_id=corr_id, cmd_id=parsed.cmd_id)


def try_dispatch_chat_cmd(text: str, *, operator_id: str | None = None) -> dict | None:
    """Return a chat-shaped response when text is a registered cmd, else None."""
    ensure_cmds_registered()
    if not is_cmd_input(text):
        return None
    parsed = parse_cmd_input(text)
    if parsed is None:
        return None
    ctx = CmdContext(operator_id=operator_id, surface=CmdSurface.DASHBOARD, raw_text=text)
    corr_id = new_corr_id()
    long_running = parsed.cmd_id in _LONG_RUNNING_CMDS
    if long_running:
        from services.async_bridge import schedule_coro
        from services.voice.hub import hub

        hub.broadcast(
            _chat_event({"type": "status", "value": "thinking"}, corr_id=corr_id),
            operator_id=operator_id,
        )
        schedule_coro(
            _run_long_cmd_async(
                parsed=parsed,
                ctx=ctx,
                text=text,
                corr_id=corr_id,
                operator_id=operator_id,
            )
        )
        return _immediate_pending_response(corr_id=corr_id, cmd_id=parsed.cmd_id)
    from services.async_bridge import run_sync

    result = run_sync(dispatch_cmd_async(parsed, ctx))
    result = _ensure_cmd_result(result, cmd_id=parsed.cmd_id)
    return _broadcast_cmd_turn(
        text=text,
        reply=result,
        operator_id=operator_id,
        cmd_id=parsed.cmd_id,
    )


async def dispatch_cmd_request(
    *,
    text: str | None = None,
    cmd_id: str | None = None,
    args: dict | None = None,
    operator_id: str | None = None,
    surface: CmdSurface = CmdSurface.DISCORD,
    metadata: dict | None = None,
) -> CmdResult:
    ensure_cmds_registered()
    ctx = CmdContext(
        operator_id=operator_id,
        surface=surface,
        raw_text=text or "",
        metadata=metadata or {},
    )
    if text:
        parsed = parse_cmd_input(text)
        if parsed is None:
            return CmdResult(ok=False, error="not a registered cmd")
        return await dispatch_cmd_async(parsed, ctx)
    if cmd_id:
        cmd = registry.get(cmd_id)
        if cmd is None:
            return CmdResult(ok=False, error=f"unknown cmd: {cmd_id}")
        parsed = ParsedCmd(cmd_id=cmd.id, name=cmd.name, args=args or {})
        return await dispatch_cmd_async(parsed, ctx)
    return CmdResult(ok=False, error="text or cmd_id required")
