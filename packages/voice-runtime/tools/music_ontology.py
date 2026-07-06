"""Music ontology lookup tools for the voice agent."""

from __future__ import annotations

from typing import Any, Callable

from .registry import ToolSpec


def build_music_ontology_tools(*, emit: Callable[..., None] | None = None) -> list[ToolSpec]:
    del emit  # lookup is read-only; play uses dashboard_player

    def music_lookup(args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query") or "").strip()
        if not query:
            return {"ok": False, "error": "query required"}
        from services.music.ontology import lookup_sync

        meta = lookup_sync(query)
        if meta is None:
            return {
                "ok": True,
                "found": False,
                "query": query,
                "message": "No confident ontology match for that query.",
            }
        return {
            "ok": True,
            "found": True,
            "title": meta.title,
            "artist": meta.artist,
            "work_key": meta.work_key,
            "aliases": meta.aliases,
            "confidence": meta.confidence,
            "source_refs": [r.model_dump() for r in meta.source_refs],
            "matched_via": meta.matched_via,
        }

    return [
        ToolSpec(
            name="music_lookup",
            description=(
                "Look up canonical music identity (work title, artist, cross-source refs) "
                "via the music ontology. Use when the user asks what a track is, who made it, "
                "or where it lives across sources — not for playback (use dashboard_play_music)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Artist and track text, e.g. 'M83 - Midnight City'.",
                    },
                },
                "required": ["query"],
            },
            handler=music_lookup,
            group="integrations",
            execution_timeout=15.0,
        ),
    ]
