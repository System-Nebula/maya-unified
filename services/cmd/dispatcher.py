"""Execute registered cmds."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from opentelemetry import trace

from services.cmd.capabilities import check_cmd_permissions
from services.cmd.models import CmdContext, CmdResult, ParsedCmd
from services.cmd.parser import validate_args
from services.cmd.registry import registry

_tracer = trace.get_tracer("maya.cmd")


def _cmd_trace_id() -> str | None:
    try:
        from maya_image.service import current_trace_id
    except ImportError:
        span = trace.get_current_span()
        ctx = span.get_span_context()
        if not ctx.is_valid:
            return None
        return format(ctx.trace_id, "032x")
    return current_trace_id()


async def dispatch_cmd_async(parsed: ParsedCmd, ctx: CmdContext) -> CmdResult:
    cmd = registry.get(parsed.cmd_id)
    if cmd is None:
        return CmdResult(ok=False, error=f"unknown cmd: {parsed.name}")
    if ctx.surface not in cmd.surfaces:
        return CmdResult(
            ok=False,
            error=f"cmd {cmd.name} is not available on surface {ctx.surface.value}",
        )
    denied = check_cmd_permissions(cmd, parsed, ctx)
    if denied:
        return CmdResult(ok=False, error=denied)
    err = validate_args(cmd, parsed.args)
    if err:
        return CmdResult(ok=False, error=err)
    if cmd.executor is None:
        return CmdResult(ok=False, error=f"cmd {cmd.name} has no executor")
    with _tracer.start_as_current_span("cmd.dispatch") as span:
        span.set_attribute("cmd.id", parsed.cmd_id)
        span.set_attribute("cmd.surface", ctx.surface.value)
        corr_id = (ctx.metadata or {}).get("corr_id")
        if corr_id:
            span.set_attribute("chat.corr_id", str(corr_id))
        try:
            result = cmd.executor(ctx, parsed.args)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, CmdResult):
                if result.job_id:
                    span.set_attribute("image.job_id", result.job_id)
                if not result.ok and not result.trace_id:
                    result = result.model_copy(update={"trace_id": _cmd_trace_id()})
                elif result.ok and not result.trace_id:
                    result = result.model_copy(update={"trace_id": _cmd_trace_id()})
                return result
            return CmdResult(ok=True, text=str(result))
        except Exception as exc:  # noqa: BLE001
            return CmdResult(ok=False, error=str(exc), trace_id=_cmd_trace_id())


def dispatch_cmd(parsed: ParsedCmd, ctx: CmdContext) -> CmdResult:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(dispatch_cmd_async(parsed, ctx))
    raise RuntimeError("dispatch_cmd called from async context; use dispatch_cmd_async")


def dispatch_text(text: str, ctx: CmdContext) -> CmdResult | None:
    from services.cmd.parser import parse_cmd_input

    parsed = parse_cmd_input(text)
    if parsed is None:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(dispatch_cmd_async(parsed, ctx))
    return loop.run_until_complete(dispatch_cmd_async(parsed, ctx))
