"""Per-operator data directory helpers."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from services.paths import DATA_DIR, ROOT


def operator_data_dir(operator_id: str | uuid.UUID) -> Path:
    path = DATA_DIR / "operators" / str(operator_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_memory_dir(operator_id: str | uuid.UUID) -> Path:
    path = operator_data_dir(operator_id) / "memory"
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_skills_dir(operator_id: str | uuid.UUID) -> Path:
    path = operator_data_dir(operator_id) / "skills"
    path.mkdir(parents=True, exist_ok=True)
    return path


def room_data_dir(room_id: str | uuid.UUID) -> Path:
    path = DATA_DIR / "rooms" / str(room_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def sync_personalities_file(operator_id: str | uuid.UUID, active: str, personalities: dict) -> Path:
    """Write personalities.json under operator dir for voice-runtime PersonalityStore."""
    data_dir = operator_data_dir(operator_id)
    payload = {"active": active, "personalities": personalities}
    path = data_dir / "personalities.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def sync_settings_file(operator_id: str | uuid.UUID, settings: dict) -> Path:
    path = operator_data_dir(operator_id) / "settings.json"
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_legacy_global_settings() -> dict:
    from services.settings.store import load_settings

    return load_settings()


def load_legacy_global_personalities() -> dict:
    path = DATA_DIR / "personalities.json"
    if not path.is_file():
        examples = ROOT / "examples" / "personalities" / "personalities.json"
        if examples.is_file():
            return json.loads(examples.read_text(encoding="utf-8"))
        return {"active": "default", "personalities": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def seed_operator_dirs(operator_id: str | uuid.UUID) -> None:
    operator_memory_dir(operator_id)
    operator_skills_dir(operator_id)
    for name in ("USER.md", "MEMORY.md"):
        mem = operator_memory_dir(operator_id) / name
        if not mem.is_file():
            mem.write_text("", encoding="utf-8")
