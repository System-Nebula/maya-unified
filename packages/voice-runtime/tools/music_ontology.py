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

    def music_index_url(args: dict[str, Any]) -> dict[str, Any]:
        url = str(args.get("url") or "").strip()
        if not url:
            return {"ok": False, "error": "url required"}
        from services.music.url_handler import index_music_url_sync

        resolved = index_music_url_sync(url, correlate=bool(args.get("correlate", True)))
        if resolved is None:
            return {"ok": True, "found": False, "url": url, "message": "No tracklist found."}
        return {
            "ok": True,
            "found": True,
            "set_key": resolved.set_key,
            "title": resolved.title,
            "container_url": resolved.container_url,
            "entry_count": len(resolved.entries),
            "entries": [
                {
                    "position": e.position,
                    "start_seconds": e.start_seconds,
                    "label": e.label,
                    "artist": e.artist,
                    "title": e.title,
                    "work_key": e.work_key,
                }
                for e in resolved.entries
            ],
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
        ToolSpec(
            name="music_index_url",
            description=(
                "Index a DJ set URL (YouTube mix, 1001tracklists, Apple Music album) "
                "and return parsed timestamped tracklist entries with ontology enrichment."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "YouTube, 1001tracklists, or Apple Music album URL.",
                    },
                    "correlate": {
                        "type": "boolean",
                        "description": "Merge linked cross-source tracklists when found.",
                    },
                },
                "required": ["url"],
            },
            handler=music_index_url,
            group="integrations",
            execution_timeout=30.0,
        ),
    ]
