"""Cast dashboard mini-player audio to a Discord voice channel."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from services.dashboard.player import player_snapshot

log = logging.getLogger("maya-unified.discord_cast")

_casting: dict[str, bool] = {}


def _operator_key(operator_id: str | None) -> str | None:
    oid = (operator_id or "").strip()
    return oid or None


def _discord_manager() -> Any | None:
    from services.voice.hub import hub

    if not getattr(hub, "ready", False) or hub.agent is None:
        return None
    return getattr(hub.agent, "discord", None)


def is_casting(*, operator_id: str | None = None) -> bool:
    key = _operator_key(operator_id)
    return bool(key and _casting.get(key))


def _track_query(track: dict[str, Any]) -> str:
    q = str(track.get("query") or track.get("title") or "").strip()
    if not q:
        raise ValueError("Track has no query or title")
    return q


async def cast_status(*, operator_id: str | None = None) -> dict[str, Any]:
    discord = _discord_manager()
    casting = is_casting(operator_id=operator_id)
    if discord is None:
        return {
            "available": False,
            "casting": casting,
            "reason": "Discord bot is not running — start the voice agent first.",
        }
    try:
        playback = await asyncio.to_thread(discord.playback_status)
        status = await asyncio.to_thread(discord.status)
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "casting": casting,
            "reason": str(exc),
        }
    voice_info = (status or {}).get("voice") or {}
    connected = bool(playback.get("connected"))
    return {
        "available": True,
        "casting": casting,
        "connected": connected,
        "channel": voice_info.get("channel"),
        "now_playing": voice_info.get("now_playing") or playback.get("now_playing"),
        "queue_length": playback.get("queue_length"),
    }


async def _push_snapshot_to_discord(
    snapshot: dict[str, Any],
    *,
    channel_name: str | None = None,
) -> dict[str, Any]:
    discord = _discord_manager()
    if discord is None:
        raise RuntimeError("Discord bot is not running — start the voice agent first.")

    tracks = snapshot.get("tracks") or []
    if not tracks:
        raise ValueError("Nothing in the dashboard player to cast.")

    current = int(snapshot.get("current") or 0)
    current = max(0, min(current, len(tracks) - 1))

    if channel_name and str(channel_name).strip():
        await asyncio.to_thread(discord.join_voice, str(channel_name).strip())

    first = await asyncio.to_thread(discord.play_youtube, _track_query(tracks[current]))
    queued = 0
    for track in tracks[current + 1 :]:
        try:
            await asyncio.to_thread(discord.queue_youtube, _track_query(track))
            queued += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("cast queue failed for %r: %s", track, exc)
            break

    return {
        "channel": first.get("channel"),
        "now_playing": first.get("playing"),
        "queued": queued,
        "track_index": current,
    }


async def start_cast(
    *,
    operator_id: str | None = None,
    channel_name: str | None = None,
) -> dict[str, Any]:
    snapshot = player_snapshot(operator_id)
    if snapshot is None:
        raise ValueError("Load a track in the player before casting to Discord.")

    result = await _push_snapshot_to_discord(snapshot, channel_name=channel_name)
    key = _operator_key(operator_id)
    if key:
        _casting[key] = True
    result["casting"] = True
    return result


async def sync_cast(*, operator_id: str | None = None) -> dict[str, Any]:
    key = _operator_key(operator_id)
    if not key or not _casting.get(key):
        return {"synced": False, "reason": "not casting"}
    snapshot = player_snapshot(operator_id)
    if snapshot is None:
        return {"synced": False, "reason": "no player snapshot"}
    result = await _push_snapshot_to_discord(snapshot)
    result["synced"] = True
    result["casting"] = True
    return result


async def stop_cast(*, operator_id: str | None = None) -> dict[str, Any]:
    key = _operator_key(operator_id)
    if key:
        _casting[key] = False

    discord = _discord_manager()
    if discord is None:
        return {"casting": False, "stopped": False, "reason": "Discord bot not running"}

    try:
        result = await asyncio.to_thread(discord.stop_music)
    except Exception as exc:  # noqa: BLE001
        return {"casting": False, "stopped": False, "reason": str(exc)}
    return {"casting": False, "stopped": bool(result.get("stopped")), **result}
