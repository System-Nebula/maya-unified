"""Named personality presets — SillyTavern-style character cards + fast swap."""

from __future__ import annotations

import json
import os
import re
import time
from typing import TYPE_CHECKING, Any, Optional

from .character_card import (
    card_from_legacy_prompt,
    compile_character_prompt,
    empty_card,
    export_v2,
    normalize_card,
    normalize_import,
)
from .user_profile import resolve_user_name

if TYPE_CHECKING:
    from config import Config

_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


def _path(data_dir: str) -> str:
    return os.path.join(data_dir, "personalities.json")


def _slug(name: str) -> str:
    return _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-") or "persona"


def _load_raw(data_dir: str) -> dict[str, Any]:
    path = _path(data_dir)
    if not os.path.isfile(path):
        return {"active": "", "personalities": {}}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {"active": "", "personalities": {}}
        data.setdefault("active", "")
        data.setdefault("personalities", {})
        if not isinstance(data["personalities"], dict):
            data["personalities"] = {}
        return data
    except (OSError, TypeError, ValueError):
        return {"active": "", "personalities": {}}


def _save_raw(data_dir: str, data: dict[str, Any]) -> None:
    os.makedirs(data_dir, exist_ok=True)
    with open(_path(data_dir), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def _entry_card(entry: dict[str, Any]) -> dict[str, Any]:
    if isinstance(entry.get("card"), dict):
        return normalize_card(entry["card"])
    name = str(entry.get("name") or "Character")
    prompt = str(entry.get("prompt") or "").strip()
    if prompt:
        return card_from_legacy_prompt(name, prompt)
    return empty_card(name)


def _compile_entry(
    entry: dict[str, Any],
    *,
    data_dir: str = "",
    user_name: str | None = None,
) -> tuple[str, str]:
    card = _entry_card(entry)
    if card.get("name") in ("", "Character"):
        card["name"] = str(entry.get("name") or card.get("name") or "Character")
    if user_name is None:
        user_name = resolve_user_name(data_dir) if data_dir else "the user"
    return compile_character_prompt(card, user_name=user_name)


class PersonalityStore:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self._ensure_seeded()

    def _ensure_seeded(self) -> None:
        data = _load_raw(self.data_dir)
        if data["personalities"]:
            return
        from memory.settings_store import load_settings

        settings = load_settings(self.data_dir)
        prompt = settings.get("system_prompt")
        if not (isinstance(prompt, str) and prompt.strip()):
            try:
                from config import CONFIG

                prompt = CONFIG.llm.system_prompt
            except Exception:  # noqa: BLE001
                prompt = ""
        if isinstance(prompt, str) and prompt.strip():
            card = card_from_legacy_prompt("Default", prompt.strip())
            system, post = compile_character_prompt(
                card, user_name=resolve_user_name(self.data_dir),
            )
            data["personalities"]["default"] = {
                "name": "Default",
                "prompt": system,
                "post_history": post,
                "card": card,
                "updated": time.time(),
            }
            data["active"] = "default"
            _save_raw(self.data_dir, data)

    def list(self) -> dict[str, Any]:
        data = _load_raw(self.data_dir)
        items = []
        for pid, entry in sorted(
            data["personalities"].items(),
            key=lambda kv: (kv[1].get("name") or kv[0]).lower(),
        ):
            card = _entry_card(entry)
            tags = card.get("tags") or []
            items.append({
                "id": pid,
                "name": entry.get("name") or card.get("name") or pid,
                "preview": str(entry.get("prompt") or "")[:120],
                "tags": tags[:6],
                "updated": entry.get("updated"),
            })
        active = data.get("active") or ""
        if active and active not in data["personalities"] and items:
            active = items[0]["id"]
        return {"active": active, "personalities": items}

    def get_active_state(self) -> tuple[Optional[str], str, str, dict[str, Any]]:
        data = _load_raw(self.data_dir)
        active = data.get("active") or ""
        entry = data["personalities"].get(active)
        if not entry:
            return None, "", "", empty_card()
        prompt, post = _compile_entry(entry, data_dir=self.data_dir)
        card = _entry_card(entry)
        return active, prompt, post, card

    def get_active_prompt(self) -> Optional[str]:
        _, prompt, _, _ = self.get_active_state()
        return prompt or None

    def get(self, personality_id: str) -> Optional[dict[str, Any]]:
        data = _load_raw(self.data_dir)
        entry = data["personalities"].get(personality_id)
        if not entry:
            return None
        card = _entry_card(entry)
        prompt, post = _compile_entry(entry, data_dir=self.data_dir)
        return {
            "id": personality_id,
            "name": entry.get("name") or card.get("name") or personality_id,
            "prompt": prompt,
            "post_history": post,
            "card": card,
            "creator_notes": str(card.get("creator_notes") or ""),
        }

    def save(
        self,
        name: str,
        prompt: str = "",
        personality_id: str = "",
        card: Optional[dict[str, Any]] = None,
        *,
        activate: bool = True,
    ) -> dict[str, Any]:
        name = (name or "").strip() or "Character"
        pid = (personality_id or "").strip() or _slug(name)

        if card is not None:
            normalized = normalize_card({**card, "name": name})
        elif prompt.strip():
            normalized = card_from_legacy_prompt(name, prompt.strip())
        else:
            return {"ok": False, "error": "card or prompt is required"}

        system, post = compile_character_prompt(
            normalized, user_name=resolve_user_name(self.data_dir),
        )
        if not system.strip():
            return {"ok": False, "error": "compiled prompt is empty"}

        data = _load_raw(self.data_dir)
        data["personalities"][pid] = {
            "name": name,
            "prompt": system,
            "post_history": post,
            "card": normalized,
            "updated": time.time(),
        }
        if activate:
            data["active"] = pid
        _save_raw(self.data_dir, data)
        return {
            "ok": True,
            "id": pid,
            "name": name,
            "active": data["active"],
            "prompt": system,
            "post_history": post,
            "card": normalized,
        }

    def import_card(self, raw: Any, *, activate: bool = True) -> dict[str, Any]:
        card = normalize_import(raw)
        name = (card.get("name") or "Imported").strip() or "Imported"
        pid = _slug(name)
        data = _load_raw(self.data_dir)
        if pid in data["personalities"]:
            pid = f"{pid}-{int(time.time())}"
        return self.save(name, personality_id=pid, card=card, activate=activate)

    def export_card(self, personality_id: str) -> dict[str, Any]:
        got = self.get(personality_id)
        if not got:
            return {"ok": False, "error": "personality not found"}
        return {"ok": True, "export": export_v2(got["card"])}

    def activate(self, personality_id: str) -> dict[str, Any]:
        pid = (personality_id or "").strip()
        data = _load_raw(self.data_dir)
        entry = data["personalities"].get(pid)
        if not entry:
            return {"ok": False, "error": "personality not found"}
        data["active"] = pid
        _save_raw(self.data_dir, data)
        got = self.get(pid) or {}
        return {
            "ok": True,
            "id": pid,
            "name": got.get("name") or pid,
            "prompt": got.get("prompt") or "",
            "post_history": got.get("post_history") or "",
            "card": got.get("card") or empty_card(),
            "creator_notes": got.get("creator_notes") or "",
        }

    def delete(self, personality_id: str) -> dict[str, Any]:
        pid = (personality_id or "").strip()
        data = _load_raw(self.data_dir)
        if pid not in data["personalities"]:
            return {"ok": False, "error": "personality not found"}
        if len(data["personalities"]) <= 1:
            return {"ok": False, "error": "cannot delete the only personality"}
        del data["personalities"][pid]
        if data.get("active") == pid:
            data["active"] = next(iter(data["personalities"]))
        _save_raw(self.data_dir, data)
        got = self.get(data["active"]) or {}
        return {
            "ok": True,
            "active": data["active"],
            "prompt": got.get("prompt") or "",
            "post_history": got.get("post_history") or "",
            "card": got.get("card") or empty_card(),
        }


def apply_persisted_personality(config: "Config") -> None:
    data_dir = config.memory.resolve_data_dir()
    store = PersonalityStore(data_dir)
    prompt = store.get_active_prompt()
    if prompt:
        config.llm.system_prompt = prompt
        return
    from memory.settings_store import apply_persisted_settings

    apply_persisted_settings(config)


def persist_active_personality(config: "Config", prompt: str, card: Optional[dict] = None) -> None:
    data_dir = config.memory.resolve_data_dir()
    store = PersonalityStore(data_dir)
    listing = store.list()
    active = listing.get("active") or ""
    if card is not None:
        entry = store.get(active) if active else None
        name = (entry or {}).get("name") or (card.get("name") or "Character")
        store.save(name, card=card, personality_id=active or "", activate=True)
        return
    if active:
        entry = store.get(active)
        if entry:
            card = dict(entry.get("card") or empty_card(entry.get("name", "")))
            card["system_prompt"] = prompt.strip()
            store.save(entry["name"], card=card, personality_id=active, activate=True)
            return
    store.save("Default", prompt=prompt, personality_id="default", activate=True)
