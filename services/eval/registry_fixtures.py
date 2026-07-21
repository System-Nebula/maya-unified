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
    query_lower = query.lower()
    if "bitcoin" in query_lower or "btc" in query_lower:
        results = [{
            "title": "Bitcoin price — July 20, 2026 close",
            "snippet": "Bitcoin closed at $65,238.30, up 0.80% for the day.",
            "url": "https://example.test/markets/bitcoin-2026-07-20",
        }]
    elif "oracle" in query_lower or "orcl" in query_lower:
        results = [{
            "title": "Oracle (ORCL) stock — July 20, 2026 close",
            "snippet": "Oracle closed at $122.19, down 3.34% for the day.",
            "url": "https://example.test/markets/orcl-2026-07-20",
        }]
    elif "olivia rodrigo" in query_lower:
        results = [{
            "title": "Olivia Rodrigo — latest album",
            "snippet": (
                "Her third studio album, You Seem Pretty Sad for a Girl So in Love, "
                "was released June 12, 2026 and has 13 tracks."
            ),
            "url": "https://example.test/music/olivia-rodrigo-latest-album",
        }]
    else:
        results = [{"title": f"Stub result for {query}"}]
    return {"ok": True, "query": query, "results": results, "stub": True}


# Deterministic fact tools — fixed payloads so grounding is checkable offline.
def _get_current_datetime(args: dict) -> dict[str, Any]:
    return {
        "weekday": "Monday",
        "date": "2026-07-20",
        "time": "9:05 PM",
        "iso": "2026-07-20T21:05:00-05:00",
        "tz": "CDT",
        "spoken": "Monday, July 20th, 9:05 PM",
        "stub": True,
    }


def _get_air_quality(args: dict) -> dict[str, Any]:
    location = str(args.get("location") or "your area").strip() or "your area"
    return {
        "location": location,
        "us_aqi": 42,
        "category": "good",
        "pm2_5": 8.1,
        "spoken": f"Air quality in {location} is good, with a US AQI of 42.",
        "stub": True,
    }


def _weather(args: dict) -> dict[str, Any]:
    location = str(args.get("location") or "your area").strip() or "your area"
    return {
        "location": location,
        "now": "Clear +64°F",
        "detail": "Clear, 64°F, humidity 55%",
        "spoken": f"It's clear and about 64 degrees in {location} tonight.",
        "stub": True,
    }


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
            ToolSpec(
                name="get_current_datetime",
                description=(
                    "Get the current local date and time. Use for any 'what day/date is it', "
                    "'what time is it', 'what's today' question."
                ),
                parameters={"type": "object", "properties": {}, "required": []},
                handler=_get_current_datetime,
                group="eval",
            ),
            ToolSpec(
                name="get_air_quality",
                description=(
                    "Get current air quality (US AQI, PM2.5) for a place. Use when asked about "
                    "air quality, smog, pollution, or whether the air is safe."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "City or place name (optional)."},
                    },
                    "required": [],
                },
                handler=_get_air_quality,
                group="eval",
            ),
            ToolSpec(
                name="weather",
                description=(
                    "Get current weather / temperature for a city or place. Use when the user "
                    "asks about weather, temperature, or the forecast."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "City or place name (optional)."},
                    },
                    "required": [],
                },
                handler=_weather,
                group="eval",
            ),
        ]
    )
    return registry
