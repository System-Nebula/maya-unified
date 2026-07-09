"""/queue cmd — append music to the dashboard player without interrupting playback."""

from __future__ import annotations

from typing import Any

from services.cmd.models import CmdContext, CmdResult, CmdSurface
from services.cmd.play_query import extract_cmd_query_from_raw_text, looks_like_cmd_residue


def _extract_query(ctx: CmdContext) -> str:
    return extract_cmd_query_from_raw_text(ctx.raw_text or "", cmd="queue")


async def exec_queue(ctx: CmdContext, args: dict[str, Any]) -> CmdResult:
    query = _extract_query(ctx)
    if not query:
        return CmdResult(
            ok=False,
            error="Give me a link or search text to queue — e.g. /queue gangnam style.",
        )
    if looks_like_cmd_residue(query):
        return CmdResult(
            ok=False,
            error="Queue query still looks like a command — paste only the URL or search text.",
        )
    if ctx.surface not in (CmdSurface.DASHBOARD, CmdSurface.CHAT):
        return CmdResult(ok=False, error="/queue is for the dashboard music player.")

    from services.dashboard.resolve import schedule_queue_resolve

    after_current = bool(args.get("after_current", False))
    schedule_queue_resolve(query, operator_id=ctx.operator_id, after_current=after_current)
    where = "up next" if after_current else "the queue"
    return CmdResult(ok=True, text=f"Looking up “{query}” for {where}…")
