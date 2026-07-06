"""/queue cmd — append music to the dashboard player without interrupting playback."""

from __future__ import annotations

from typing import Any

from services.cmd.models import CmdContext, CmdResult, CmdSurface


def _extract_query(ctx: CmdContext) -> str:
    raw = (ctx.raw_text or "").strip()
    body = raw[1:].strip() if raw.startswith("/") else raw
    parts = body.split(None, 1)
    return parts[1].strip() if len(parts) > 1 else ""


async def exec_queue(ctx: CmdContext, args: dict[str, Any]) -> CmdResult:
    query = _extract_query(ctx)
    if not query:
        return CmdResult(
            ok=False,
            error="Give me a link or search text to queue — e.g. /queue gangnam style.",
        )
    if ctx.surface not in (CmdSurface.DASHBOARD, CmdSurface.CHAT):
        return CmdResult(ok=False, error="/queue is for the dashboard music player.")

    from services.dashboard.resolve import schedule_queue_resolve

    after_current = bool(args.get("after_current", False))
    schedule_queue_resolve(query, operator_id=ctx.operator_id, after_current=after_current)
    where = "up next" if after_current else "the queue"
    return CmdResult(ok=True, text=f"Looking up “{query}” for {where}…")
