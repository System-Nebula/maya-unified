"""Persist UI settings (system prompt, etc.) under the data directory."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from config import Config


def _path(data_dir: str) -> str:
    return os.path.join(data_dir, "settings.json")


def load_settings(data_dir: str) -> dict[str, Any]:
    path = _path(data_dir)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, TypeError, ValueError):
        return {}


def save_settings(data_dir: str, updates: dict[str, Any]) -> None:
    os.makedirs(data_dir, exist_ok=True)
    current = load_settings(data_dir)
    current.update(updates)
    with open(_path(data_dir), "w", encoding="utf-8") as fh:
        json.dump(current, fh, indent=2, ensure_ascii=False)


def apply_persisted_settings(config: "Config") -> None:
    """Load saved UI settings over env defaults at startup."""
    data_dir = config.memory.resolve_data_dir()
    settings = load_settings(data_dir)
    prompt = settings.get("system_prompt")
    if isinstance(prompt, str) and prompt.strip():
        config.llm.system_prompt = prompt.strip()


def persist_system_prompt(config: "Config", prompt: str) -> None:
    save_settings(config.memory.resolve_data_dir(), {"system_prompt": prompt.strip()})
