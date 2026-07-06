"""/play cmd executor — play music in the dashboard sticky player and/or Discord.

On the dashboard/chat surface it loads the shared sticky player (streamed
same-origin via ``/api/media/stream``) and returns status text only in chat.
When the Discord bot is connected it also queues the same tracks into the voice channel.
On the Discord surface it queues to voice only.
"""

from __future__ import annotations

import asyncio
from typing import Any

from services.cmd.models import CmdContext, CmdResult, CmdSurface


def _extract_query(ctx: CmdContext) -> str:
    raw = (ctx.raw_text or "").strip()
    body = raw[1:].strip() if raw.startswith("/") else raw
    parts = body.split(None, 1)
    return parts[1].strip() if len(parts) > 1 else ""


def _queue_discord(discord, query: str, expansion) -> int:
    if expansion is not None and expansion.tracks:
        queued = 0
        for url, _title in expansion.tracks:
            try:
                discord.queue_youtube(url)
                queued += 1
            except ValueError:
                break
        return queued
    try:
        discord.queue_youtube(query)
        return 1
    except Exception:  # noqa: BLE001
        return 0


def _resume_text(result: dict[str, Any]) -> str:
    now = result.get("now_playing") or result.get("playing")
    if result.get("resumed") is False:
        reason = result.get("reason") or "nothing is paused"
        return f"Couldn't resume — {reason}."
    if now:
        return f"Resumed {now}."
    return "Resumed playback."


async def _expand_query(query: str):
    from services.discord.playlist import expand_playlist

    try:
        return await asyncio.to_thread(expand_playlist, query)
    except Exception:  # noqa: BLE001
        return None


async def exec_play(ctx: CmdContext, args: dict[str, Any]) -> CmdResult:
    query = _extract_query(ctx)
    web_surface = ctx.surface in (CmdSurface.DASHBOARD, CmdSurface.CHAT)

    from services.voice.hub import hub

    discord = None
    if getattr(hub, "ready", False) and hub.agent is not None:
        discord = getattr(hub.agent, "discord", None)

    if not query:
        if web_surface:
            from services.dashboard.player import broadcast_player_control

            broadcast_player_control("resume", operator_id=ctx.operator_id)
            return CmdResult(ok=True, text="Resuming playback.")
        if discord is not None:
            try:
                result = await asyncio.to_thread(discord.resume_playback)
            except Exception as exc:  # noqa: BLE001
                return CmdResult(ok=False, error=str(exc))
            return CmdResult(ok=True, text=_resume_text(result if isinstance(result, dict) else {}))
        return CmdResult(
            ok=False,
            error="Give me a link, Bandcamp album, or search text to play — e.g. /play <url>.",
        )

    if not web_surface and discord is None:
        return CmdResult(
            ok=False,
            error="Discord playback isn't running — start the voice agent / connect the Discord bot first.",
        )

    from services.dashboard.player import broadcast_player_load, build_playlist_artifact

    from services.music.ontology import build_playlist_from_resolution, resolve_for_play

    resolved = await resolve_for_play(query)
    if resolved is not None:
        playlist = build_playlist_from_resolution(query, resolved)
        expansion = None
        track_total = len(playlist.get("tracks") or [])
        title = resolved.title or query
    else:
        expansion = await _expand_query(query)
        track_total = len(expansion.tracks) if (expansion and expansion.tracks) else 1
        title = (expansion.title if expansion else "") or query
        playlist = None

    if web_surface:
        if playlist is None:
            playlist = build_playlist_artifact(query, expansion)
        broadcast_player_load(playlist, operator_id=ctx.operator_id)

    queued_discord = 0
    if discord is not None:
        discord_query = resolved.play_url if resolved is not None else query
        queued_discord = await asyncio.to_thread(_queue_discord, discord, discord_query, expansion)

    noun = "track" if track_total == 1 else "tracks"
    if track_total > 1:
        head = f"Queued {track_total} {noun} from “{title}”"
    else:
        head = f"Now playing “{title}”"

    if web_surface and queued_discord:
        text = f"{head} — here and in Discord."
    elif web_surface:
        text = f"{head}."
    else:
        d_total = queued_discord or track_total
        d_noun = "track" if d_total == 1 else "tracks"
        text = f"Queued {d_total} {d_noun} from “{title}” in Discord."

    return CmdResult(ok=True, text=text)
