"""Bandcamp wishlist voice tools."""

from __future__ import annotations

from typing import Any, Callable

from .registry import ToolSpec


def _operator_context() -> tuple[str | None, dict[str, Any], str]:
    from services.settings.store import load_effective_settings
    from services.voice.hub import hub

    operator_id = hub._active_operator_id
    settings = load_effective_settings(operator_id)
    hint = getattr(hub, "_last_user_text", "") or ""
    return operator_id, settings, hint


def _resolve_bandcamp_username(args: dict, settings: dict[str, Any], hint: str) -> str:
    from services.integrations.bandcamp import resolve_username

    explicit = str(args.get("username") or "").strip()
    return resolve_username(settings, hint=hint, explicit=explicit)


def _run_bandcamp(fn, *, timeout: float = 60):
    from services.async_bridge import run_sync
    import asyncio

    async def _call():
        return await asyncio.to_thread(fn)

    return run_sync(_call(), timeout=timeout)


def build_bandcamp_tools(*, emit: Callable[..., None] | None = None) -> list[ToolSpec]:
    def _emit_player_load(playlist: dict[str, Any]) -> None:
        if emit is not None:
            emit(type="player.load", playlist=playlist)
        else:
            from services.dashboard.player import broadcast_player_load
            from services.voice.hub import hub

            broadcast_player_load(playlist, operator_id=hub._active_operator_id)

    def read_wishlist(args: dict) -> dict[str, Any]:
        limit = args.get("limit", 10)
        offset = args.get("offset", 0)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 10
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            offset = 0

        from services.integrations.bandcamp import (
            BandcampError,
            BandcampRateLimited,
            BandcampWishlistPrivate,
            ensure_username_configured,
            format_wishlist_speech,
            list_wishlist,
        )

        operator_id, settings, hint = _operator_context()
        username = _resolve_bandcamp_username(args, settings, hint)
        if not username:
            return {
                "ok": False,
                "error": (
                    "Bandcamp username not found. Pass a bandcamp.com/username URL "
                    "or set bandcamp.username in Settings."
                ),
            }
        ensure_username_configured(operator_id, username)

        try:
            result = _run_bandcamp(
                lambda: list_wishlist(username, limit=limit, offset=offset),
                timeout=45,
            )
        except BandcampWishlistPrivate:
            return {
                "ok": False,
                "error": "Your Bandcamp wishlist is private. Connect with a session cookie (not yet supported).",
            }
        except BandcampRateLimited:
            return {
                "ok": False,
                "error": "Bandcamp rate limited the request. Try again in a few minutes.",
            }
        except BandcampError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Bandcamp wishlist lookup failed: {exc}"}

        message = format_wishlist_speech(result)
        return {
            "ok": True,
            "message": message,
            "username": result.get("username"),
            "total": result.get("total_count"),
            "offset": result.get("offset"),
            "items": result.get("items"),
        }

    def play_wishlist_tool(args: dict) -> dict[str, Any]:
        from services.integrations.bandcamp import (
            BandcampError,
            BandcampRateLimited,
            BandcampWishlistPrivate,
            ensure_username_configured,
            play_wishlist,
        )

        filter_text = str(args.get("filter") or args.get("genre") or "").strip()
        limit = args.get("limit", 5)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 5

        operator_id, settings, hint = _operator_context()
        username = _resolve_bandcamp_username(args, settings, hint)
        if not username:
            return {
                "ok": False,
                "error": (
                    "Bandcamp username not found. Pass a bandcamp.com/username URL "
                    "or set bandcamp.username in Settings."
                ),
            }
        ensure_username_configured(operator_id, username)

        try:
            result = _run_bandcamp(
                lambda: play_wishlist(username, filter_text=filter_text, limit=limit),
                timeout=90,
            )
        except BandcampWishlistPrivate:
            return {
                "ok": False,
                "error": "Your Bandcamp wishlist is private. Connect with a session cookie (not yet supported).",
            }
        except BandcampRateLimited:
            return {
                "ok": False,
                "error": "Bandcamp rate limited the request. Try again in a few minutes.",
            }
        except BandcampError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Bandcamp wishlist playback failed: {exc}"}

        if not result.get("ok"):
            return result

        playlist = result.get("playlist")
        if isinstance(playlist, dict) and playlist.get("tracks"):
            _emit_player_load(playlist)

        return {
            "ok": True,
            "message": result.get("message") or "Queued wishlist tracks.",
            "queued": result.get("queued"),
            "items": result.get("items"),
            "username": result.get("username"),
        }

    return [
        ToolSpec(
            name="bandcamp_read_wishlist",
            description=(
                "Read or list items from the operator's Bandcamp wishlist aloud. Use when "
                "the user asks what's on their wishlist or wants items read out. Extract "
                "username from any bandcamp.com/username URL in the message. Do not web-search."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "Optional Bandcamp fan username (or parse from URL).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "How many items to read (default 10, max 25).",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Skip this many items for pagination (default 0).",
                    },
                },
            },
            handler=read_wishlist,
            group="integrations",
        ),
        ToolSpec(
            name="bandcamp_play_wishlist",
            description=(
                "Play or queue music from the operator's Bandcamp wishlist in the dashboard "
                "player. Use when they ask to queue, play, or filter wishlist items (e.g. DNB, "
                "jungle, drum and bass). Extract username from bandcamp.com URLs. Do not web-search."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "Optional Bandcamp fan username (or parse from URL).",
                    },
                    "filter": {
                        "type": "string",
                        "description": "Genre or keyword filter, e.g. dnb, jungle, artist name.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max wishlist albums/tracks to queue (default 5, max 10).",
                    },
                },
            },
            handler=play_wishlist_tool,
            group="integrations",
        ),
    ]
