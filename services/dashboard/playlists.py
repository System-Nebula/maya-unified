"""Operator-scoped saved playlists for the dashboard player."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "", value or "")


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "playlist").lower()).strip("-")
    return (slug[:48] or "playlist")


def _playlist_dir(operator_id: str) -> Path:
    safe = _safe_id(operator_id)
    if not safe:
        raise ValueError("operator_id required")
    path = DATA / "operators" / safe / "playlists"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_playlists(operator_id: str) -> list[dict[str, Any]]:
    directory = _playlist_dir(operator_id)
    items: list[dict[str, Any]] = []
    for file in directory.glob("*.json"):
        try:
            raw = json.loads(file.read_text(encoding="utf-8"))
            items.append(
                {
                    "id": raw.get("id") or file.stem,
                    "name": raw.get("name") or "Untitled",
                    "trackCount": len(raw.get("tracks") or []),
                    "savedAt": raw.get("savedAt"),
                }
            )
        except (OSError, json.JSONDecodeError):
            continue
    items.sort(key=lambda x: x.get("savedAt") or "", reverse=True)
    return items


def get_playlist(operator_id: str, playlist_id: str) -> dict[str, Any]:
    safe = _safe_id(playlist_id)
    if not safe:
        raise ValueError("Invalid playlist id")
    path = _playlist_dir(operator_id) / f"{safe}.json"
    if not path.is_file():
        raise FileNotFoundError("Playlist not found")
    raw = json.loads(path.read_text(encoding="utf-8"))
    tracks = raw.get("tracks") or []
    if not tracks:
        raise ValueError("Playlist has no tracks")
    return raw


def save_playlist(operator_id: str, *, name: str, tracks: list[dict[str, Any]]) -> dict[str, Any]:
    label = (name or "").strip()
    if not label:
        raise ValueError("name is required")
    if not tracks:
        raise ValueError("tracks are required")
    playlist_id = f"{_slugify(label)}-{int(datetime.now(timezone.utc).timestamp() * 1000)}"
    data = {
        "id": playlist_id,
        "name": label,
        "tracks": tracks,
        "savedAt": datetime.now(timezone.utc).isoformat(),
    }
    path = _playlist_dir(operator_id) / f"{playlist_id}.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def delete_playlist(operator_id: str, playlist_id: str) -> None:
    safe = _safe_id(playlist_id)
    if not safe:
        raise ValueError("Invalid playlist id")
    path = _playlist_dir(operator_id) / f"{safe}.json"
    if not path.is_file():
        raise FileNotFoundError("Playlist not found")
    path.unlink()
