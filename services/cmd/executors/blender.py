"""Blender MCP slash command executor."""

from __future__ import annotations

import shlex
from typing import Any

from services.blender import (
    blender_inspect_file,
    blender_render,
    blender_run_code,
    blender_screenshot,
    blender_summary,
)
from services.cmd.models import CmdContext, CmdResult

_ACTIONS = frozenset({"summary", "inspect", "screenshot", "render", "code"})


def _parse_blend_args(ctx: CmdContext, args: dict[str, Any]) -> dict[str, Any]:
    """Parse action/file/code from slash input beyond generic cmd token mapping."""
    raw = (ctx.raw_text or "").strip()
    body = raw[1:].strip() if raw.startswith("/") else raw
    if not body:
        action = str(args.get("action") or "summary").strip().lower()
        if action not in _ACTIONS:
            action = "summary"
        out: dict[str, Any] = {"action": action}
        if args.get("file"):
            out["file"] = str(args["file"])
        if args.get("code"):
            out["code"] = str(args["code"])
        return out

    parts = body.split(None, 1)
    raw_args = parts[1].strip() if len(parts) > 1 else ""

    if not raw_args:
        return {"action": "summary"}

    try:
        tokens = shlex.split(raw_args)
    except ValueError:
        tokens = raw_args.split()

    first = tokens[0].lower() if tokens else "summary"
    if first not in _ACTIONS:
        return {"action": "summary"}

    rest = raw_args[len(tokens[0]) :].strip()
    if first == "code":
        return {"action": "code", "code": rest}
    if first == "inspect":
        return {"action": "inspect", "file": rest}
    return {"action": first}


async def exec_blend(ctx: CmdContext, args: dict[str, Any]) -> CmdResult:
    parsed = _parse_blend_args(ctx, args)
    action = parsed.get("action", "summary")

    try:
        if action == "summary":
            result = await blender_summary()
            return _result_from_tool(result, prefix="Blender scene summary")

        if action == "inspect":
            blend_file = str(parsed.get("file") or "").strip()
            if not blend_file:
                return CmdResult(ok=False, error="missing required parameter: file")
            result = await blender_inspect_file(blend_file)
            return _result_from_tool(result, prefix=f"Inspect {blend_file}")

        if action == "screenshot":
            result, artifacts = await blender_screenshot()
            return _result_from_tool(result, prefix="Blender screenshot", artifacts=artifacts)

        if action == "render":
            result, artifacts = await blender_render()
            return _result_from_tool(result, prefix="Blender render", artifacts=artifacts)

        if action == "code":
            code = str(parsed.get("code") or "").strip()
            if not code:
                return CmdResult(ok=False, error="missing required parameter: code")
            blend_file = str(args.get("file") or "").strip() or None
            result, artifacts = await blender_run_code(code=code, blend_file=blend_file)
            return _result_from_tool(result, prefix="Blender code result", artifacts=artifacts)

        return CmdResult(ok=False, error=f"unknown action: {action}")
    except Exception as exc:  # noqa: BLE001
        return CmdResult(ok=False, error=str(exc))


def _result_from_tool(
    result,
    *,
    prefix: str,
    artifacts: list[dict[str, Any]] | None = None,
) -> CmdResult:
    if result.is_error:
        return CmdResult(ok=False, error=result.text or "blender tool failed")
    text = result.text.strip()
    if text and text != "ok":
        body = f"{prefix}:\n{text}"
    else:
        body = prefix
    out_artifacts = list(artifacts or [])
    if not out_artifacts and result.images:
        from services.blender.artifacts import artifact_from_bytes

        out_artifacts = [artifact_from_bytes(img) for img in result.images]
    if out_artifacts:
        urls = ", ".join(a.get("url", "") for a in out_artifacts if a.get("url"))
        if urls:
            body = f"{body}\n{urls}"
    return CmdResult(ok=True, text=body, artifacts=out_artifacts)
