"""Shared dashboard music player helpers for /play cmd and voice tools."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote


def stream_src(q: str) -> str:
    return f"/api/media/stream?q={quote(q, safe='')}"


def _track_payload(*, query: str, title: str, index: int) -> dict[str, str]:
    label = (title or "").strip() or f"Track {index + 1}"
    q = (query or "").strip()
    return {"title": label, "query": q, "src": stream_src(q)}


def build_playlist_artifact(query: str, expansion) -> dict[str, Any]:
    if expansion is not None and expansion.tracks:
        tracks = [
            _track_payload(query=url, title=title, index=i)
            for i, (url, title) in enumerate(expansion.tracks)
        ]
        album = expansion.title or "Playlist"
    else:
        q = (query or "").strip()
        tracks = [_track_payload(query=q, title=q, index=0)]
        album = q
    return {"type": "playlist", "title": album, "url": query, "tracks": tracks}


async def build_playlist_for_query(query: str) -> dict[str, Any]:
    from services.discord.playlist import expand_playlist

    # Ontology-first: canonical work → known/enriched recording URL. Returns
    # None for direct URLs and unconfident matches — then legacy expansion
    # runs unchanged. Every confident play also warms the graph write-through.
    try:
        from services.music.ontology import (
            build_playlist_from_resolution,
            resolve_for_play,
        )

        resolved = await resolve_for_play(query)
    except Exception:  # noqa: BLE001 — ontology must never break playback
        resolved = None
    if resolved is not None:
        return build_playlist_from_resolution(query, resolved)

    try:
        expansion = await asyncio.to_thread(expand_playlist, query)
    except Exception:  # noqa: BLE001
        expansion = None
    return build_playlist_artifact(query, expansion)


@dataclass
class _OperatorPlayerState:
    playlist: dict[str, Any]
    current: int = 0


_player_cache: dict[str, _OperatorPlayerState] = {}


def _cache_key(operator_id: str | None) -> str | None:
    oid = (operator_id or "").strip()
    return oid or None


def remember_player_load(playlist: dict[str, Any], *, operator_id: str | None = None) -> None:
    key = _cache_key(operator_id)
    if not key or not playlist.get("tracks"):
        return
    _player_cache[key] = _OperatorPlayerState(playlist=dict(playlist), current=0)


def remember_player_control(
    action: str,
    *,
    operator_id: str | None = None,
    index: int | None = None,
) -> None:
    key = _cache_key(operator_id)
    if not key:
        return
    act = (action or "").strip().lower()
    if act == "clear":
        clear_player_state(operator_id=operator_id)
        return
    state = _player_cache.get(key)
    if state is None:
        return
    tracks = state.playlist.get("tracks") or []
    if act in {"skip", "next"} and state.current + 1 < len(tracks):
        state.current += 1
    elif act in {"previous", "back", "prev"} and state.current > 0:
        state.current -= 1
    elif act == "play" and index is not None and 0 <= index < len(tracks):
        state.current = index


def clear_player_state(*, operator_id: str | None = None) -> None:
    key = _cache_key(operator_id)
    if key:
        _player_cache.pop(key, None)


def clear_player_and_broadcast(*, operator_id: str | None = None) -> None:
    """Clear server-side player cache and notify connected dashboards."""
    clear_player_state(operator_id=operator_id)
    broadcast_player_control("clear", operator_id=operator_id)


def player_snapshot(operator_id: str | None) -> dict[str, Any] | None:
    key = _cache_key(operator_id)
    if not key:
        return None
    state = _player_cache.get(key)
    if state is None:
        return None
    playlist = dict(state.playlist)
    playlist["current"] = state.current
    return playlist


def replay_player_to_subscriber(q: Any, *, operator_id: str | None = None) -> None:
    snapshot = player_snapshot(operator_id)
    if not snapshot:
        return
    q.put({"type": "player.load", "playlist": snapshot, "operator_id": operator_id})


def broadcast_player_load(playlist: dict[str, Any], *, operator_id: str | None = None) -> None:
    from services.voice.hub import hub

    remember_player_load(playlist, operator_id=operator_id)
    hub.broadcast({"type": "player.load", "playlist": playlist}, operator_id=operator_id)


def remember_player_append(
    artifact: dict[str, Any],
    *,
    operator_id: str | None = None,
    after_current: bool = False,
) -> dict[str, Any]:
    """Merge new tracks into the cached playlist; return the full playlist."""
    key = _cache_key(operator_id)
    incoming = list(artifact.get("tracks") or [])
    if not incoming:
        return dict(artifact)

    if key and key in _player_cache:
        state = _player_cache[key]
        existing = list(state.playlist.get("tracks") or [])
        insert_at = (state.current + 1) if after_current else len(existing)
        insert_at = max(0, min(insert_at, len(existing)))
        merged_tracks = existing[:insert_at] + incoming + existing[insert_at:]
        state.playlist = {
            **state.playlist,
            "tracks": merged_tracks,
        }
        return dict(state.playlist)

    playlist = dict(artifact)
    if key:
        _player_cache[key] = _OperatorPlayerState(playlist=playlist, current=0)
    return playlist


def broadcast_player_append(
    artifact: dict[str, Any],
    *,
    operator_id: str | None = None,
    after_current: bool = False,
) -> dict[str, Any]:
    from services.voice.hub import hub

    playlist = remember_player_append(
        artifact,
        operator_id=operator_id,
        after_current=after_current,
    )
    hub.broadcast(
        {
            "type": "player.append",
            "playlist": playlist,
            "tracks": artifact.get("tracks") or [],
            "after_current": after_current,
        },
        operator_id=operator_id,
    )
    return playlist


def broadcast_player_control(
    action: str,
    *,
    operator_id: str | None = None,
    index: int | None = None,
) -> None:
    from services.voice.hub import hub

    remember_player_control(action, operator_id=operator_id, index=index)
    payload: dict[str, Any] = {"type": "player.control", "action": action}
    if index is not None:
        payload["index"] = index
    hub.broadcast(payload, operator_id=operator_id)
