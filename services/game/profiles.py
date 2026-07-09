"""Load YAML game profiles for the vision game bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[2]
PROFILES_DIR = _ROOT / "data" / "game_profiles"


@dataclass
class GameActionSpec:
    name: str
    description: str
    schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class GameProfile:
    id: str
    display_name: str
    emulator: str
    capture: dict[str, Any]
    input: dict[str, Any]
    actions: list[GameActionSpec]
    turn_policy: dict[str, Any]
    prompt_guide: str = ""
    playbook: dict[str, Any] = field(default_factory=dict)

    def neuro_actions(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for a in self.actions:
            entry: dict[str, Any] = {
                "name": a.name,
                "description": a.description,
            }
            if a.schema:
                entry["schema"] = a.schema
            out.append(entry)
        return out


def _parse_profile(raw: dict[str, Any], path: Path) -> GameProfile:
    pid = str(raw.get("id") or path.stem).strip()
    actions_raw = raw.get("actions") or []
    actions: list[GameActionSpec] = []
    for item in actions_raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        actions.append(
            GameActionSpec(
                name=name,
                description=str(item.get("description") or name),
                schema=dict(item.get("schema") or {}),
            )
        )
    return GameProfile(
        id=pid,
        display_name=str(raw.get("display_name") or pid),
        emulator=str(raw.get("emulator") or ""),
        capture=dict(raw.get("capture") or {}),
        input=dict(raw.get("input") or {}),
        actions=actions,
        turn_policy=dict(raw.get("turn_policy") or {}),
        prompt_guide=str(raw.get("prompt_guide") or "").strip(),
        playbook=dict(raw.get("playbook") or {}),
    )


def list_profile_ids() -> list[str]:
    if not PROFILES_DIR.is_dir():
        return []
    ids: list[str] = []
    for path in sorted(PROFILES_DIR.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        ids.append(path.stem)
    return ids


def load_profile(profile_id: str) -> GameProfile:
    pid = str(profile_id or "").strip()
    if not pid:
        raise ValueError("profile_id required")
    path = PROFILES_DIR / f"{pid}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"game profile not found: {pid}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"invalid profile YAML: {path}")
    profile = _parse_profile(raw, path)
    if profile.id != pid and path.stem == pid:
        profile.id = pid
    return profile


def list_profiles() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for pid in list_profile_ids():
        try:
            p = load_profile(pid)
            out.append(
                {
                    "id": p.id,
                    "display_name": p.display_name,
                    "emulator": p.emulator,
                    "action_count": len(p.actions),
                }
            )
        except Exception:
            continue
    return out
