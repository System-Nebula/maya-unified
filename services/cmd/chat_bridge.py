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


def _chat_event(payload: dict, *, corr_id: str, message_id: str | None = None) -> dict:
    out = dict(payload)
    out["corr_id"] = corr_id
    if message_id:
        out["message_id"] = message_id
    return out


def _broadcast_cmd_turn(
    *,
    text: str,
    reply: CmdResult,
    operator_id: str | None,
) -> dict:
    from services.voice.hub import hub

    corr_id = new_corr_id()
    user_message_id = new_message_id()
    reply_message_id = new_message_id()
    hub.broadcast(
        _chat_event({"type": "user", "text": text}, corr_id=corr_id, message_id=user_message_id),
        operator_id=operator_id,
    )
    if reply.ok:
        ai_payload: dict = {"type": "ai", "text": reply.text, "mode": "cmd"}
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
        err_text = reply.error or reply.text or "command failed"
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
    out = reply.to_chat_response()
    out["corr_id"] = corr_id
    if reply.trace_id:
        out["trace_id"] = reply.trace_id
    if reply.job_id:
        out["job_id"] = reply.job_id
    return out


def try_dispatch_chat_cmd(text: str, *, operator_id: str | None = None) -> dict | None:
    """Return a chat-shaped response when text is a registered cmd, else None."""
    ensure_cmds_registered()
    if not is_cmd_input(text):
        return None
    parsed = parse_cmd_input(text)
    if parsed is None:
        return None
    ctx = CmdContext(operator_id=operator_id, surface=CmdSurface.DASHBOARD, raw_text=text)
    from services.voice.hub import hub

    if parsed.cmd_id in {"imagine", "blend"}:
        hub.broadcast(
            _chat_event({"type": "status", "value": "thinking"}, corr_id=new_corr_id()),
            operator_id=operator_id,
        )
    result = asyncio.run(dispatch_cmd_async(parsed, ctx))
    return _broadcast_cmd_turn(text=text, reply=result, operator_id=operator_id)


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
