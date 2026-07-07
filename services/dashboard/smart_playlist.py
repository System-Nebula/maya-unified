"""LLM smart playlists and radio refill for the dashboard player."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

log = logging.getLogger("maya-unified.dashboard.smart_playlist")

PLAN_SYSTEM = """You are a DJ playlist engine. Output a single JSON object only. No markdown, no code fences.

{
  "name": "short playlist title",
  "rationale": "one sentence",
  "tracks": [
    {"artist": "Artist Name", "title": "Song Title", "searchQuery": "optional yt-dlp query"},
    ...
  ]
}

Rules:
- Output 15-30 tracks in the tracks array.
- Format each pick as Artist — Song (artist and title fields). Real songs only.
- searchQuery: optional YouTube search override. Defaults to artist + title.
- Do NOT include audioUrl, artUrl, bpm, key, or genre."""

RADIO_PLAN_SYSTEM = """You are an infinite radio DJ. Output a single JSON object only. No markdown, no code fences.

{
  "name": "short segment title",
  "rationale": "one sentence",
  "tracks": [
    {"artist": "Artist Name", "title": "Song Title", "searchQuery": "optional yt-dlp query"},
    ...
  ]
}

Rules:
- Output 8-12 NEW tracks per request — this is a refill segment, not a full playlist.
- Match the vibe, genre, era, or scene described. Vary artists.
- NEVER repeat any song listed in the exclude / already-played list.
- Format each pick as Artist — Song. Real songs only.
- searchQuery: optional YouTube search override.
- Do NOT include audioUrl, artUrl, bpm, key, or genre."""


def _extract_json(text: str) -> dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
    body = fenced.group(1) if fenced else text
    start = body.find("{")
    end = body.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("LLM response missing JSON object")
    return json.loads(body[start : end + 1])


def _suggestion_to_track(raw: dict[str, Any], idx: int) -> dict[str, str]:
    artist = str(raw.get("artist") or "").strip()
    title = str(raw.get("title") or "Untitled").strip()
    query = str(raw.get("searchQuery") or f"{artist} {title}".strip()).strip()
    if not query:
        query = title
    return {"title": title, "artist": artist, "query": query}


async def _llm_plan(
    *,
    operator_id: str | None,
    system: str,
    user: str,
    temperature: float = 0.65,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    from services.llm.provider import create_llm_client

    client = create_llm_client(operator_id=operator_id)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    if hasattr(client, "complete"):
        resp = client.complete(messages, max_tokens=max_tokens)
        content = getattr(resp, "content", None) or ""
    else:
        content = client.client.chat.completions.create(
            model=client.cfg.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        ).choices[0].message.content or ""
    if not content.strip():
        raise ValueError("LLM returned empty response")
    parsed = _extract_json(content)
    tracks = parsed.get("tracks") or []
    if not isinstance(tracks, list) or not tracks:
        raise ValueError("LLM returned zero tracks")
    return {
        "name": str(parsed.get("name") or "SMART PLAYLIST"),
        "rationale": str(parsed.get("rationale") or ""),
        "tracks": tracks,
    }


def _fallback_tracks(prompt: str, *, count: int = 15) -> list[dict[str, str]]:
    words = [w for w in re.split(r"\s+", prompt.lower()) if len(w) > 2][:6]
    base = " ".join(words) if words else "instrumental"
    return [
        _suggestion_to_track(
            {"artist": "Various", "title": f"{base.title()} mix {i + 1}", "searchQuery": f"{base} {i + 1}"},
            i,
        )
        for i in range(count)
    ]


async def stream_smart_playlist(
    prompt: str,
    emit: Callable[[str, dict[str, Any]], None],
    *,
    operator_id: str | None = None,
) -> None:
    text = (prompt or "").strip()
    if not text:
        raise ValueError("prompt is required")
    emit("status", {"message": "PLANNING PLAYLIST…"})
    try:
        plan = await _llm_plan(
            operator_id=operator_id,
            system=PLAN_SYSTEM,
            user=f"User request:\n{text}",
            max_tokens=8192,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("smart playlist LLM failed, using fallback: %s", exc)
        tracks = _fallback_tracks(text)
        emit("meta", {"name": "LOCAL HEURISTIC", "rationale": str(exc), "total": len(tracks)})
        for i, tr in enumerate(tracks):
            emit("track", tr)
        return

    suggestions = plan["tracks"]
    emit(
        "meta",
        {
            "name": plan["name"],
            "rationale": plan["rationale"],
            "total": len(suggestions),
        },
    )
    emit("status", {"message": f"RESOLVING {len(suggestions):02d} TRACKS…"})
    for i, raw in enumerate(suggestions):
        if not isinstance(raw, dict):
            continue
        emit("track", _suggestion_to_track(raw, i))


async def stream_radio_refill(
    prompt: str,
    emit: Callable[[str, dict[str, Any]], None],
    *,
    operator_id: str | None = None,
    exclude: list[str] | None = None,
) -> None:
    text = (prompt or "").strip()
    if not text:
        raise ValueError("prompt is required")
    skip = [s for s in (exclude or []) if isinstance(s, str) and s.strip()]
    exclude_block = ""
    if skip:
        exclude_block = "\nAlready in rotation (DO NOT repeat):\n" + "\n".join(
            f"- {s}" for s in skip[-50:]
        )
    emit("status", {"message": "RADIO — PLANNING NEXT SEGMENT…"})
    try:
        plan = await _llm_plan(
            operator_id=operator_id,
            system=RADIO_PLAN_SYSTEM,
            user=f"{exclude_block}\n\nVibe / radio request:\n{text}",
            temperature=0.75,
            max_tokens=4096,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("radio refill LLM failed, using fallback: %s", exc)
        tracks = _fallback_tracks(text, count=10)
        emit("meta", {"name": "RADIO SEGMENT", "rationale": str(exc), "total": len(tracks)})
        for tr in tracks:
            emit("track", tr)
        return

    suggestions = plan["tracks"]
    emit(
        "meta",
        {"name": plan["name"], "rationale": plan["rationale"], "total": len(suggestions)},
    )
    for i, raw in enumerate(suggestions):
        if not isinstance(raw, dict):
            continue
        emit("track", _suggestion_to_track(raw, i))


SMART_PLAYLIST_TIMEOUT = 120.0


def plan_smart_playlist_blocking(
    prompt: str,
    *,
    operator_id: str | None = None,
    timeout: float = SMART_PLAYLIST_TIMEOUT,
) -> dict[str, Any]:
    """LLM playlist plan for agent tools (no per-track URL resolution)."""
    from services.async_bridge import run_sync

    text = (prompt or "").strip()
    if not text:
        raise ValueError("prompt required")
    tracks: list[dict[str, str]] = []
    meta: dict[str, Any] = {"title": "Smart Playlist"}

    def emit(ev_type: str, data: dict[str, Any]) -> None:
        if ev_type == "meta":
            meta["title"] = data.get("name") or meta["title"]
            meta["rationale"] = data.get("rationale")
        elif ev_type == "track":
            tracks.append(data)

    run_sync(stream_smart_playlist(text, emit, operator_id=operator_id), timeout=timeout)
    if not tracks:
        raise ValueError("no tracks planned")
    return {
        "title": meta["title"],
        "tracks": tracks,
        "url": text,
        "rationale": meta.get("rationale"),
    }
