"""Build dashboard playlist artifacts from correlated DJ sets."""

from __future__ import annotations

from typing import Any

from maya_feeds.youtube_setlist import extract_youtube_video_id
from services.dashboard.player import stream_src
from services.music.set_types import PLATFORM_YOUTUBE, ResolvedSet, SetEntry


def _entry_payload(entry: SetEntry) -> dict[str, Any]:
    row: dict[str, Any] = {
        "position": entry.position,
        "start_seconds": entry.start_seconds,
        "end_seconds": entry.end_seconds,
        "label": entry.label,
        "artist": entry.artist,
        "title": entry.title,
        "attrs": dict(entry.attrs),
    }
    if entry.work_key:
        row["work_key"] = entry.work_key
    if entry.source_refs:
        row["source_refs"] = [r.model_dump() for r in entry.source_refs]
    return row


def _virtual_track(
    *,
    entry: SetEntry,
    resolved: ResolvedSet,
    container_url: str,
) -> dict[str, Any]:
    play_q = entry.play_url or container_url
    duration = None
    if entry.end_seconds is not None and entry.start_seconds is not None:
        duration = max(0, entry.end_seconds - entry.start_seconds)
    track: dict[str, Any] = {
        "title": entry.label,
        "query": play_q,
        "src": stream_src(play_q),
        "start_offset": entry.start_seconds,
        "end_offset": entry.end_seconds,
        "duration": duration,
        "position": entry.position,
        "play_mode": entry.play_mode,
        "set_key": resolved.set_key,
    }
    if entry.artist:
        track["artist"] = entry.artist
    if entry.work_key:
        track["work_key"] = entry.work_key
    if entry.source_refs:
        track["source_refs"] = [r.model_dump() for r in entry.source_refs]
    return track


def _video_id_for_set(resolved: ResolvedSet) -> str | None:
    if resolved.container_schema == PLATFORM_YOUTUBE:
        _, _, ext = resolved.set_key.partition(":")
        if ext:
            return ext
        return extract_youtube_video_id(resolved.container_url)
    return None


def is_set_presentation(resolved: ResolvedSet) -> bool:
    if len(resolved.entries) < 2:
        return False
    container = (resolved.container_url or "").strip()
    if not container:
        return False
    return all(
        (e.play_url or container).strip() == container or e.play_mode == "seek"
        for e in resolved.entries
    )


def build_set_artifact(query: str, resolved: ResolvedSet) -> dict[str, Any]:
    """Rich live-set artifact for dashboard adaptive presentation."""
    container_url = resolved.container_url
    entries = [_entry_payload(e) for e in resolved.entries]
    tracks = [
        _virtual_track(entry=e, resolved=resolved, container_url=container_url)
        for e in resolved.entries
    ]
    video_id = _video_id_for_set(resolved)
    duration = resolved.attrs.get("duration_seconds")
    linked = [r.model_dump() for r in resolved.linked_sets]

    set_id = resolved.set_key.split(":", 1)[-1] if ":" in resolved.set_key else resolved.set_key

    return {
        "type": "playlist",
        "presentation": "set",
        "mode": "live_set",
        "title": resolved.title,
        "url": query,
        "set_key": resolved.set_key,
        "set_id": set_id,
        "container_url": container_url,
        "container_schema": resolved.container_schema,
        "video_id": video_id,
        "duration_seconds": duration,
        "venue": resolved.attrs.get("venue"),
        "date": resolved.attrs.get("date"),
        "linked_sets": linked,
        "entries": entries,
        "tracks": tracks,
    }


def build_playlist_from_set(query: str, resolved: ResolvedSet) -> dict[str, Any]:
    if is_set_presentation(resolved):
        return build_set_artifact(query, resolved)

    tracks = [
        _virtual_track(entry=e, resolved=resolved, container_url=resolved.container_url)
        for e in resolved.entries
    ]
    return {
        "type": "playlist",
        "presentation": "playlist",
        "title": resolved.title,
        "url": query,
        "set_key": resolved.set_key,
        "tracks": tracks,
    }
