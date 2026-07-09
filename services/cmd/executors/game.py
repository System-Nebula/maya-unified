"""/game cmd — start autonomous emulator play toward a goal."""

from __future__ import annotations

import asyncio
from typing import Any

from services.cmd.models import CmdContext, CmdResult


def _voice_hub():
    from services.voice.hub import hub

    return hub


def _extract_goal(ctx: CmdContext, args: dict[str, Any]) -> str:
    goal = str(args.get("goal") or "").strip()
    if goal:
        return goal
    raw = (ctx.raw_text or "").strip()
    body = raw[1:].strip() if raw.startswith("/") else raw
    parts = body.split(None, 1)
    if len(parts) > 1:
        text = parts[1].strip()
        # Strip profile=... kv tail for goal text
        if " profile=" in text:
            text = text.split(" profile=", 1)[0].strip()
        if text:
            return text
    return ""


async def exec_game(ctx: CmdContext, args: dict[str, Any]) -> CmdResult:
    goal = _extract_goal(ctx, args)
    if not goal:
        return CmdResult(
            ok=False,
            error="Usage: /game <goal>  e.g. /game reach the end of the game",
        )
    profile_id = str(args.get("profile_id") or args.get("profile") or "pokemon_gba").strip()

    hub = _voice_hub()
    if not getattr(hub, "ready", False) or hub.agent is None:
        return CmdResult(ok=False, error="Voice agent not ready — wait for Maya to finish loading.")

    oid = ctx.operator_id or hub._active_operator_id

    def _start_game() -> str | None:
        h = _voice_hub()
        if oid:
            h.apply_operator_context(oid)
        return h.agent._run_game_play_until_goal(  # noqa: SLF001
            goal,
            profile_id=profile_id,
        )

    try:
        reply = await asyncio.to_thread(_start_game)
    except Exception as exc:  # noqa: BLE001
        return CmdResult(ok=False, error=str(exc))

    if not reply:
        return CmdResult(ok=False, error="Could not start game mode.")
    return CmdResult(ok=True, text=reply)
