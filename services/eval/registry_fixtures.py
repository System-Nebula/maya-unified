"""Minimal tool registry with stub handlers for eval (no side effects)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_VOICE_RUNTIME = Path(__file__).resolve().parents[2] / "packages" / "voice-runtime"
if str(_VOICE_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_VOICE_RUNTIME))

from tools.registry import ToolRegistry, ToolSpec  # noqa: E402


def _stub_ok(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "stub": True, "tool": tool, "args": args}


def _play_music(args: dict) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "query required"}
    return {
        "ok": True,
        "message": f"Queued “{query}”.",
        "title": query,
        "tracks": 1,
        "stub": True,
    }


def _imagine_generate(args: dict) -> dict[str, Any]:
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return {"ok": False, "error": "prompt required"}
    return {
        "ok": True,
        "url": "/imagine-outputs/stub.png",
        "prompt": prompt,
        "model": "stub",
        "job_id": "eval-stub",
        "stub": True,
    }


def _music_lookup(args: dict) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "query required"}
    return {
        "ok": True,
        "found": True,
        "title": query.title(),
        "artist": "Stub Artist",
        "work_key": "stub:work",
        "stub": True,
    }


def _web_search(args: dict) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    return {"ok": True, "results": [{"title": f"Stub result for {query}"}], "stub": True}


def build_eval_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_many(
        [
            ToolSpec(
                name="dashboard_play_music",
                description=(
                    "Play music in the dashboard browser player. Pass a URL or search text."
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
            handler=_play_music,
            group="eval",
        ),
        ToolSpec(
            name="dashboard_queue_music",
            description="Add music to the dashboard player queue.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "after_current": {"type": "boolean"},
                },
                "required": ["query"],
            },
            handler=lambda a: _stub_ok("dashboard_queue_music", a),
            group="eval",
        ),
        ToolSpec(
            name="dashboard_pause_music",
                description="Pause the dashboard music player.",
                parameters={"type": "object", "properties": {}},
                handler=lambda a: _stub_ok("dashboard_pause_music", a),
                group="eval",
            ),
            ToolSpec(
                name="imagine_generate",
                description="Generate an image from a text prompt.",
                parameters={
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "What to generate"},
                        "model": {"type": "string"},
                        "size": {"type": "string"},
                    },
                    "required": ["prompt"],
                },
                handler=_imagine_generate,
                group="eval",
            ),
            ToolSpec(
                name="music_lookup",
                description="Look up canonical music identity via the ontology.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Artist and track text"},
                    },
                    "required": ["query"],
                },
                handler=_music_lookup,
                group="eval",
            ),
            ToolSpec(
                name="web_search",
                description="Search the web for current information.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                    },
                    "required": ["query"],
                },
                handler=_web_search,
                group="eval",
            ),
        ]
    )
    return registry
