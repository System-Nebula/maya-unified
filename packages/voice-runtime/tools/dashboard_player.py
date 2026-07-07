"""Dashboard sticky music player tools — remote control for the in-browser player."""

from __future__ import annotations

from typing import Any, Callable

from .registry import ToolSpec


def build_dashboard_player_tools(*, emit: Callable[..., None] | None = None) -> list[ToolSpec]:
    def _emit_control(action: str, *, index: int | None = None) -> None:
        if emit is not None:
            payload: dict[str, Any] = {"type": "player.control", "action": action}
            if index is not None:
                payload["index"] = index
            emit(**payload)
        else:
            from services.dashboard.player import broadcast_player_control
            from services.voice.hub import hub

            broadcast_player_control(action, operator_id=hub._active_operator_id, index=index)

    def _operator_id() -> str | None:
        if emit is not None:
            return None
        from services.voice.hub import hub

        return hub._active_operator_id

    def play_music(args: dict) -> dict[str, Any]:
        query = str(args.get("query") or "").strip()
        if not query:
            return {"ok": False, "error": "query required"}
        if args.get("sync"):
            from services.dashboard.resolve import resolve_playlist_blocking
            from services.dashboard.player import broadcast_player_load, remember_player_load

            artifact = resolve_playlist_blocking(query)
            if emit is not None:
                emit(type="player.load", playlist=artifact)
                remember_player_load(artifact, operator_id=_operator_id())
            else:
                broadcast_player_load(artifact, operator_id=_operator_id())
            tracks = artifact.get("tracks") or []
            title = artifact.get("title") or query
            total = len(tracks)
            noun = "track" if total == 1 else "tracks"
            message = (
                f"Queued {total} {noun} from “{title}”."
                if total > 1
                else f"Now playing “{title}”."
            )
            return {"ok": True, "message": message, "title": title, "tracks": total}

        from services.dashboard.resolve import schedule_play_resolve

        schedule_play_resolve(query, operator_id=_operator_id(), emit=emit)
        return {"ok": True, "message": f"Looking up “{query}”…", "pending": True, "query": query}

    def queue_music(args: dict) -> dict[str, Any]:
        query = str(args.get("query") or "").strip()
        if not query:
            return {"ok": False, "error": "query required"}
        after_current = bool(args.get("after_current", False))
        if args.get("sync"):
            from services.dashboard.resolve import resolve_playlist_blocking
            from services.dashboard.player import remember_player_append

            artifact = resolve_playlist_blocking(query)
            incoming = artifact.get("tracks") or []
            if not incoming:
                return {"ok": False, "error": f"could not resolve {query!r}"}
            title = (incoming[0].get("title") if incoming else None) or artifact.get("title") or query
            merged = remember_player_append(
                artifact,
                operator_id=_operator_id(),
                after_current=after_current,
            )
            payload: dict[str, Any] = {
                "type": "player.append",
                "tracks": incoming,
                "after_current": after_current,
                "title": artifact.get("title"),
                "playlist": merged,
            }
            if emit is not None:
                emit(**payload)
            else:
                from services.voice.hub import hub

                hub.broadcast(payload, operator_id=hub._active_operator_id)
            where = "up next" if after_current else "the queue"
            added = len(incoming)
            message = (
                f"Added {added} tracks to {where}."
                if added > 1
                else f"Added “{title}” to {where}."
            )
            return {
                "ok": True,
                "message": message,
                "title": title,
                "added": added,
                "tracks": len(merged.get("tracks") or []),
            }

        from services.dashboard.resolve import schedule_queue_resolve

        schedule_queue_resolve(
            query,
            operator_id=_operator_id(),
            after_current=after_current,
            emit=emit,
        )
        where = "up next" if after_current else "the queue"
        return {
            "ok": True,
            "message": f"Looking up “{query}” for {where}…",
            "pending": True,
            "query": query,
        }

    def generate_playlist(args: dict) -> dict[str, Any]:
        prompt = str(args.get("prompt") or args.get("query") or "").strip()
        if not prompt:
            return {"ok": False, "error": "prompt required"}
        if args.get("sync"):
            from services.dashboard.player import broadcast_player_load, remember_player_load
            from services.dashboard.smart_playlist import plan_smart_playlist_blocking

            artifact = plan_smart_playlist_blocking(prompt, operator_id=_operator_id())
            if emit is not None:
                emit(type="player.load", playlist=artifact)
                remember_player_load(artifact, operator_id=_operator_id())
            else:
                broadcast_player_load(artifact, operator_id=_operator_id())
            tracks = artifact.get("tracks") or []
            title = artifact.get("title") or prompt
            total = len(tracks)
            noun = "track" if total == 1 else "tracks"
            return {
                "ok": True,
                "message": f"Built playlist “{title}” with {total} {noun}.",
                "title": title,
                "tracks": total,
            }

        from services.dashboard.resolve import schedule_smart_playlist

        schedule_smart_playlist(prompt, operator_id=_operator_id(), emit=emit)
        return {
            "ok": True,
            "message": f"Building a playlist for “{prompt}”…",
            "pending": True,
            "prompt": prompt,
        }

    def start_radio(args: dict) -> dict[str, Any]:
        prompt = str(args.get("prompt") or args.get("vibe") or args.get("query") or "").strip()
        if not prompt:
            return {"ok": False, "error": "prompt required"}
        if args.get("sync"):
            from services.dashboard.player import broadcast_player_load, remember_player_load
            from services.dashboard.resolve import _broadcast_player_radio
            from services.dashboard.smart_playlist import plan_smart_playlist_blocking

            artifact = plan_smart_playlist_blocking(prompt, operator_id=_operator_id())
            if emit is not None:
                emit(type="player.load", playlist=artifact)
                remember_player_load(artifact, operator_id=_operator_id())
                emit(type="player.radio", enabled=True, prompt=prompt)
            else:
                broadcast_player_load(artifact, operator_id=_operator_id())
                _broadcast_player_radio(
                    enabled=True,
                    prompt=prompt,
                    operator_id=_operator_id(),
                )
            tracks = artifact.get("tracks") or []
            title = artifact.get("title") or prompt
            return {
                "ok": True,
                "message": f"Radio on — “{title}” with {len(tracks)} tracks to start.",
                "title": title,
                "tracks": len(tracks),
            }

        from services.dashboard.resolve import schedule_smart_playlist

        schedule_smart_playlist(
            prompt,
            operator_id=_operator_id(),
            emit=emit,
            enable_radio=True,
        )
        return {
            "ok": True,
            "message": f"Starting radio for “{prompt}”…",
            "pending": True,
            "prompt": prompt,
        }

    return [
        ToolSpec(
            name="dashboard_play_music",
            description=(
                "Play music in the dashboard browser player (Bandcamp, YouTube, search). "
                "Replaces the current playlist. Use for play now — NOT dashboard_queue_music. "
                "Use NOT discord_play_youtube unless the user explicitly wants Discord voice music. "
                "Pass a URL or search text."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Bandcamp/YouTube URL or search words.",
                    },
                },
                "required": ["query"],
            },
            handler=play_music,
            group="dashboard",
        ),
        ToolSpec(
            name="dashboard_queue_music",
            description=(
                "Add music to the dashboard browser player queue without stopping the "
                "current track. Use when the user says queue, add to queue, play next, "
                "or play something after the current song. Pass a URL or search text."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Bandcamp/YouTube URL or search words.",
                    },
                    "after_current": {
                        "type": "boolean",
                        "description": "Insert after the now-playing track (play next). Default false = append to end.",
                    },
                },
                "required": ["query"],
            },
            handler=queue_music,
            group="dashboard",
        ),
        ToolSpec(
            name="dashboard_pause_music",
            description="Pause the dashboard in-browser music player.",
            parameters={"type": "object", "properties": {}},
            handler=lambda _a: (_emit_control("pause"), {"ok": True, "action": "pause"})[1],
            group="dashboard",
        ),
        ToolSpec(
            name="dashboard_resume_music",
            description=(
                "Resume the dashboard in-browser music player after pause or bare /play resume."
            ),
            parameters={"type": "object", "properties": {}},
            handler=lambda _a: (_emit_control("resume"), {"ok": True, "action": "resume"})[1],
            group="dashboard",
        ),
        ToolSpec(
            name="dashboard_skip_music",
            description=(
                "Skip to the next track in the dashboard music player. Use for next song, "
                "start the next song, skip track, etc."
            ),
            parameters={"type": "object", "properties": {}},
            handler=lambda _a: (_emit_control("skip"), {"ok": True, "action": "skip"})[1],
            group="dashboard",
        ),
        ToolSpec(
            name="dashboard_previous_music",
            description=(
                "Go back to the previous track in the dashboard music player. "
                "Use when the user asks to go back, play the last/previous song, or rewind one track."
            ),
            parameters={"type": "object", "properties": {}},
            handler=lambda _a: (_emit_control("previous"), {"ok": True, "action": "previous"})[1],
            group="dashboard",
        ),
        ToolSpec(
            name="dashboard_clear_music",
            description=(
                "Stop playback and clear the dashboard music player queue/playlist. "
                "Use when the user asks to clear, empty, reset, or remove the queue, playlist, "
                "or music player — not just pause."
            ),
            parameters={"type": "object", "properties": {}},
            handler=lambda _a: (
                _emit_control("clear"),
                {"ok": True, "action": "clear", "message": "Paused and cleared the playlist."},
            )[1],
            group="dashboard",
        ),
        ToolSpec(
            name="dashboard_generate_playlist",
            description=(
                "Generate a curated multi-track playlist in the dashboard browser player using "
                "the LLM DJ. Use when the user asks for a playlist, mix, vibe, genre block, or "
                "mood-based set — not a single song. Pass a natural-language prompt."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Playlist vibe, genre, era, or scene in plain language.",
                    },
                },
                "required": ["prompt"],
            },
            handler=generate_playlist,
            group="dashboard",
        ),
        ToolSpec(
            name="dashboard_start_radio",
            description=(
                "Start infinite radio mode in the dashboard player: LLM builds an initial "
                "playlist and auto-refills when the queue runs out. Use for radio, endless mix, "
                "or keep-this-vibe-going requests."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Radio vibe, genre, or scene to keep playing.",
                    },
                },
                "required": ["prompt"],
            },
            handler=start_radio,
            group="dashboard",
        ),
    ]
