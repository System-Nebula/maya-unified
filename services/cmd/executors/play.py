"""/play cmd executor — play music in the dashboard sticky player and/or Discord.

On the dashboard/chat surface it loads the shared sticky player (streamed
same-origin via ``/api/media/stream``) and returns status text only in chat.
When the Discord bot is connected it also queues the same tracks into the voice channel.
On the Discord surface it queues to voice only.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from services.cmd.models import CmdContext, CmdResult, CmdSurface

log = structlog.get_logger("maya-unified.cmd.play")
from services.cmd.play_query import extract_play_query_from_raw_text, looks_like_cmd_residue


def _extract_query(ctx: CmdContext) -> str:
    return extract_play_query_from_raw_text(ctx.raw_text or "")


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


def _play_status_text(
    *,
    playlist: dict[str, Any] | None,
    track_total: int,
    title: str,
    web_surface: bool,
    queued_discord: int,
) -> str:
    presentation = (playlist or {}).get("presentation")
    if presentation == "set" and track_total > 1:
        label = (playlist or {}).get("set_id") or title or "Set"
        head = f"Loaded {label} — {track_total} tracks (live set)"
    elif track_total > 1:
        noun = "tracks"
        head = f"Queued {track_total} {noun} from “{title}”"
    else:
        head = f"Now playing “{title}”"

    if web_surface and queued_discord:
        return f"{head} — here and in Discord."
    if web_surface:
        return f"{head}."
    d_noun = "track" if track_total == 1 else "tracks"
    d_total = queued_discord or track_total
    return f"Queued {d_total} {d_noun} from “{title}” in Discord."


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

    if looks_like_cmd_residue(query):
        return CmdResult(
            ok=False,
            error="Play query still looks like a command — paste only the URL or search text.",
        )

    if not web_surface and discord is None:
        return CmdResult(
            ok=False,
            error="Discord playback isn't running — start the voice agent / connect the Discord bot first.",
        )

    from services.dashboard.player import broadcast_player_load, build_playlist_for_query

    from services.music.ontology import build_playlist_from_resolution, resolve_for_play

    playlist = None
    expansion = None
    resolved = None

    if web_surface:
        playlist = await build_playlist_for_query(query)
        track_total = len(playlist.get("tracks") or [])
        title = playlist.get("title") or query
        if (
            track_total == 1
            and playlist.get("presentation") != "set"
            and looks_like_cmd_residue(title)
        ):
            return CmdResult(
                ok=False,
                error="Could not resolve that play query — paste only the URL or search text.",
            )
    else:
        resolved = await resolve_for_play(query)
        if resolved is not None:
            playlist = build_playlist_from_resolution(query, resolved)
            track_total = len(playlist.get("tracks") or [])
            title = resolved.title or query
        else:
            expansion = await _expand_query(query)
            track_total = len(expansion.tracks) if (expansion and expansion.tracks) else 1
            title = (expansion.title if expansion else "") or query

    corr_id = (ctx.metadata or {}).get("corr_id")
    if web_surface:
        broadcast_player_load(playlist, operator_id=ctx.operator_id, corr_id=corr_id)
        try:
            from services.voice.hub import hub

            hub.broadcast(
                {"type": "player.activate", "corr_id": corr_id},
                operator_id=ctx.operator_id,
            )
        except Exception:  # noqa: BLE001
            pass

    queued_discord = 0
    if discord is not None:
        discord_query = resolved.play_url if resolved is not None else query
        queued_discord = await asyncio.to_thread(_queue_discord, discord, discord_query, expansion)

    text = _play_status_text(
        playlist=playlist,
        track_total=track_total,
        title=title,
        web_surface=web_surface,
        queued_discord=queued_discord,
    )

    artifacts: list[dict[str, Any]] = []
    if web_surface and playlist and playlist.get("tracks"):
        artifacts.append(dict(playlist))

    if web_surface and playlist:
        log.info(
            "play_loaded",
            operator_id=ctx.operator_id,
            corr_id=corr_id,
            presentation=playlist.get("presentation"),
            track_count=track_total,
            entry_count=len(playlist.get("entries") or []),
            artifact_attached=bool(artifacts),
        )

    return CmdResult(ok=True, text=text, artifacts=artifacts)
