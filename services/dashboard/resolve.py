"""Async playlist resolution for dashboard player tools."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from services.async_bridge import run_sync

log = logging.getLogger("maya-unified.dashboard.resolve")

RESOLVE_TIMEOUT = 25.0


async def resolve_playlist(query: str) -> dict[str, Any]:
    from services.dashboard.player import build_playlist_for_query
    from services.music.ontology import build_playlist_from_resolution, resolve_for_play

    q = (query or "").strip()
    if not q:
        raise ValueError("query required")
    resolved = await resolve_for_play(q)
    if resolved is not None:
        return build_playlist_from_resolution(q, resolved)
    return await build_playlist_for_query(q)


def resolve_playlist_blocking(query: str, *, timeout: float = RESOLVE_TIMEOUT) -> dict[str, Any]:
    artifact = run_sync(resolve_playlist(query), timeout=timeout)
    if not artifact.get("tracks"):
        raise ValueError(f"could not resolve {query!r}")
    return artifact


def broadcast_player_error(message: str, *, operator_id: str | None = None) -> None:
    from services.voice.hub import hub

    hub.broadcast(
        {"type": "system", "text": message},
        operator_id=operator_id,
    )


def broadcast_player_followup(message: str, *, operator_id: str | None = None) -> None:
    from services.voice.hub import hub

    hub.broadcast(
        {"type": "ai", "text": message, "final": True},
        operator_id=operator_id,
    )


def _emit_or_broadcast(
    payload: dict[str, Any],
    *,
    operator_id: str | None,
    emit: Callable[..., None] | None,
) -> None:
    if emit is not None:
        emit(**payload)
        return
    from services.voice.hub import hub

    hub.broadcast(payload, operator_id=operator_id)


def schedule_play_resolve(
    query: str,
    *,
    operator_id: str | None,
    emit: Callable[..., None] | None = None,
) -> None:
    def _worker() -> None:
        try:
            from services.dashboard.player import broadcast_player_load, remember_player_load

            artifact = resolve_playlist_blocking(query)
            if emit is not None:
                emit(type="player.load", playlist=artifact)
                remember_player_load(artifact, operator_id=operator_id)
            else:
                broadcast_player_load(artifact, operator_id=operator_id)
            tracks = artifact.get("tracks") or []
            title = artifact.get("title") or query
            if len(tracks) > 1:
                msg = f"Queued {len(tracks)} tracks from “{title}”."
            else:
                msg = f"Now playing “{title}”."
            broadcast_player_followup(msg, operator_id=operator_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("play resolve failed for %r: %s", query, exc)
            broadcast_player_error(
                f"Couldn't find “{query}” — try a URL or different spelling.",
                operator_id=operator_id,
            )

    threading.Thread(
        target=_worker,
        daemon=True,
        name=f"play-resolve-{query[:24]}",
    ).start()


def schedule_queue_resolve(
    query: str,
    *,
    operator_id: str | None,
    after_current: bool = False,
    emit: Callable[..., None] | None = None,
) -> None:
    def _worker() -> None:
        try:
            from services.dashboard.player import remember_player_append

            artifact = resolve_playlist_blocking(query)
            incoming = artifact.get("tracks") or []
            title = (incoming[0].get("title") if incoming else None) or artifact.get("title") or query
            merged = remember_player_append(
                artifact,
                operator_id=operator_id,
                after_current=after_current,
            )
            payload: dict[str, Any] = {
                "type": "player.append",
                "tracks": incoming,
                "after_current": after_current,
                "title": artifact.get("title"),
                "playlist": merged,
            }
            _emit_or_broadcast(payload, operator_id=operator_id, emit=emit)
            where = "up next" if after_current else "the queue"
            added = len(incoming)
            if added > 1:
                msg = f"Added {added} tracks to {where}."
            else:
                msg = f"Added “{title}” to {where}."
            broadcast_player_followup(msg, operator_id=operator_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("queue resolve failed for %r: %s", query, exc)
            broadcast_player_error(
                f"Couldn't queue “{query}” — try a URL or different spelling.",
                operator_id=operator_id,
            )

    threading.Thread(
        target=_worker,
        daemon=True,
        name=f"queue-resolve-{query[:24]}",
    ).start()


def _broadcast_player_radio(
    *,
    enabled: bool,
    prompt: str,
    operator_id: str | None,
    emit: Callable[..., None] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "type": "player.radio",
        "enabled": enabled,
        "prompt": prompt,
    }
    _emit_or_broadcast(payload, operator_id=operator_id, emit=emit)


def schedule_smart_playlist(
    prompt: str,
    *,
    operator_id: str | None,
    emit: Callable[..., None] | None = None,
    enable_radio: bool = False,
) -> None:
    def _worker() -> None:
        try:
            from services.dashboard.player import broadcast_player_load, remember_player_load
            from services.dashboard.smart_playlist import plan_smart_playlist_blocking

            artifact = plan_smart_playlist_blocking(prompt, operator_id=operator_id)
            tracks = artifact.get("tracks") or []
            title = artifact.get("title") or prompt
            if emit is not None:
                emit(type="player.load", playlist=artifact)
                remember_player_load(artifact, operator_id=operator_id)
                if enable_radio:
                    emit(type="player.radio", enabled=True, prompt=prompt)
            else:
                broadcast_player_load(artifact, operator_id=operator_id)
                if enable_radio:
                    _broadcast_player_radio(
                        enabled=True,
                        prompt=prompt,
                        operator_id=operator_id,
                    )
            noun = "track" if len(tracks) == 1 else "tracks"
            mode = "radio" if enable_radio else "playlist"
            broadcast_player_followup(
                f"Built {mode} “{title}” with {len(tracks)} {noun}.",
                operator_id=operator_id,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("smart playlist failed for %r: %s", prompt, exc)
            broadcast_player_error(
                f"Couldn't build a playlist for “{prompt}”.",
                operator_id=operator_id,
            )

    threading.Thread(
        target=_worker,
        daemon=True,
        name=f"smart-playlist-{prompt[:24]}",
    ).start()
