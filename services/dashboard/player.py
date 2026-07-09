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
        presentation = "playlist" if len(tracks) > 1 else "single"
    else:
        q = (query or "").strip()
        from services.discord.playlist import is_url

        fallback_title = q if q and not is_url(q) else "Playlist"
        tracks = [_track_payload(query=q, title=fallback_title, index=0)]
        album = fallback_title
        presentation = "single"
    return {
        "type": "playlist",
        "presentation": presentation,
        "title": album,
        "url": query,
        "tracks": tracks,
    }


async def build_playlist_for_query(query: str) -> dict[str, Any]:
    import asyncio

    from services.cmd.play_query import looks_like_cmd_residue, normalize_play_query, salvage_media_url
    from services.discord.playlist import expand_playlist, is_url
    from services.tracing import corr_span

    with corr_span("play.build_playlist") as span:
        q = normalize_play_query((query or "").strip())
        if q and not is_url(q):
            salvaged = salvage_media_url(q)
            if salvaged:
                q = salvaged
        if looks_like_cmd_residue(q):
            q = salvage_media_url(q) or q
        span.set_attribute("query", q)

        if q and is_url(q):
            try:
                from services.music.url_handler import detect_platform, index_music_url
                from services.music.set_playlist import build_playlist_from_set

                if detect_platform(q):
                    resolved = await index_music_url(q, ingest=False)
                    if resolved is not None:
                        try:
                            from services.music.set_ingest import ingest_set

                            asyncio.create_task(ingest_set(resolved))
                        except Exception:  # noqa: BLE001
                            pass
                        result = build_playlist_from_set(q, resolved)
                        _stamp_playlist_span(span, result)
                        return result
            except Exception:  # noqa: BLE001 — set enrichment must not break playback
                pass

        # Ontology-first: canonical work → known/enriched recording URL. Returns
        # None for direct URLs and unconfident matches — then legacy expansion
        # runs unchanged. Every confident play also warms the graph write-through.
        try:
            from services.music.ontology import (
                build_playlist_from_resolution,
                resolve_for_play,
            )

            resolved = await resolve_for_play(q)
        except Exception:  # noqa: BLE001 — ontology must never break playback
            resolved = None
        if resolved is not None:
            result = build_playlist_from_resolution(q, resolved)
            _stamp_playlist_span(span, result)
            return result

        try:
            expansion = await asyncio.to_thread(expand_playlist, q)
        except Exception:  # noqa: BLE001
            expansion = None
        result = build_playlist_artifact(q, expansion)
        _stamp_playlist_span(span, result)
        return result


def _stamp_playlist_span(span, playlist: dict[str, Any]) -> None:
    entries = playlist.get("entries") or playlist.get("tracks") or []
    span.set_attribute("presentation", playlist.get("presentation", ""))
    span.set_attribute("title", playlist.get("title", ""))
    span.set_attribute("track_count", len(entries))


@dataclass
class _OperatorPlayerState:
    playlist: dict[str, Any]
    current: int = 0


_player_cache: dict[str, _OperatorPlayerState] = {}
_GLOBAL_PLAYER_CACHE_KEY = "__global__"


def _cache_key(operator_id: str | None) -> str | None:
    oid = (operator_id or "").strip()
    if oid:
        return oid
    try:
        from services.voice.hub import hub

        active = (getattr(hub, "_active_operator_id", None) or "").strip()
        if active:
            return active
    except Exception:  # noqa: BLE001
        pass
    return _GLOBAL_PLAYER_CACHE_KEY


def remember_player_load(playlist: dict[str, Any], *, operator_id: str | None = None) -> None:
    if not playlist.get("tracks"):
        return
    key = _cache_key(operator_id)
    if not key:
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
    """Clear server-side player cache and notify connected dashboards.

    Only broadcasts when there was actually a player to clear. Making repeated
    clears idempotent means a duplicate clear cannot fan a player.control:clear
    back out to the dashboards, which is what let a stray clear echo into a
    POST /player/clear -> broadcast -> clear feedback loop.
    """
    key = _cache_key(operator_id)
    had_state = bool(key and _player_cache.get(key) is not None)
    clear_player_state(operator_id=operator_id)
    if had_state:
        broadcast_player_control("clear", operator_id=operator_id)


def player_snapshot(operator_id: str | None) -> dict[str, Any] | None:
    for key in (_cache_key(operator_id), _GLOBAL_PLAYER_CACHE_KEY):
        if not key:
            continue
        state = _player_cache.get(key)
        if state is None:
            continue
        playlist = dict(state.playlist)
        playlist["current"] = state.current
        return playlist
    return None


def replay_player_to_subscriber(q: Any, *, operator_id: str | None = None) -> None:
    snapshot = player_snapshot(operator_id)
    if not snapshot:
        return
    q.put({"type": "player.load", "playlist": snapshot, "operator_id": operator_id})


def broadcast_player_load(
    playlist: dict[str, Any],
    *,
    operator_id: str | None = None,
    corr_id: str | None = None,
) -> None:
    from services.tracing import corr_span
    from services.voice.hub import hub

    entries = playlist.get("entries") or playlist.get("tracks") or []
    with corr_span(
        "player.broadcast",
        corr_id=corr_id,
        presentation=playlist.get("presentation", ""),
        track_count=len(entries),
        set_key=playlist.get("set_key", ""),
    ):
        remember_player_load(playlist, operator_id=operator_id)
        event: dict[str, Any] = {"type": "player.load", "playlist": playlist}
        if corr_id:
            event["corr_id"] = corr_id
        hub.broadcast(event, operator_id=operator_id)


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
