"""Personality seed from examples/maya-default.json on first run."""

from __future__ import annotations

import json
import os
from pathlib import Path

from services.paths import DATA_DIR, ROOT


def seed_personality_if_needed() -> None:
    """Copy maya-default.json into data/personalities.json when empty."""
    example = ROOT / "examples" / "personalities" / "maya-default.json"
    if not example.is_file():
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    target = DATA_DIR / "personalities.json"
    if target.is_file():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            if data.get("personalities"):
                return
        except (OSError, TypeError, ValueError):
            pass
    try:
        seed = json.loads(example.read_text(encoding="utf-8"))
        target.write_text(json.dumps(seed, indent=2, ensure_ascii=False), encoding="utf-8")
    except (OSError, TypeError, ValueError):
        pass
