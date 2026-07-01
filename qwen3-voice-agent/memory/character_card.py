"""SillyTavern-style Character Card V2 — import, export, compile to voice prompts.

Spec reference: https://github.com/bradennapier/character-cards-v2
"""

from __future__ import annotations

import copy
import re
from typing import Any, Optional

CARD_KEYS = (
    "name",
    "description",
    "personality",
    "scenario",
    "first_mes",
    "mes_example",
    "creator_notes",
    "system_prompt",
    "post_history_instructions",
    "alternate_greetings",
    "tags",
    "creator",
    "character_version",
    "extensions",
    "character_book",
)

VOICE_RULES = (
    "Voice interface rules: every reply is spoken aloud. Keep it to one–three "
    "short sentences. No markdown, lists, asterisks, stage directions, "
    "parentheses, or emojis."
)


def empty_card(name: str = "") -> dict[str, Any]:
    return {
        "name": name or "",
        "description": "",
        "personality": "",
        "scenario": "",
        "first_mes": "",
        "mes_example": "",
        "creator_notes": "",
        "system_prompt": "",
        "post_history_instructions": "",
        "alternate_greetings": [],
        "tags": [],
        "creator": "",
        "character_version": "1.0",
        "extensions": {},
        "character_book": None,
    }


def _substitute(text: str, *, char: str, user: str, original: str) -> str:
    out = text or ""
    out = out.replace("{{char}}", char).replace("{{user}}", user)
    out = out.replace("{{Char}}", char).replace("{{User}}", user)
    out = out.replace("<BOT>", char).replace("<USER>", user)
    out = out.replace("{{original}}", original)
    return out


def _lorebook_block(book: Any) -> str:
    if not isinstance(book, dict):
        return ""
    entries = book.get("entries") or []
    lines: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("enabled") is False:
            continue
        content = str(entry.get("content") or "").strip()
        if not content:
            continue
        if entry.get("constant") or str(entry.get("position", "")).lower() in {"before", "0"}:
            lines.append(content)
    if not lines:
        return ""
    return "World info:\n" + "\n".join(f"- {line}" for line in lines)


def normalize_import(raw: Any) -> dict[str, Any]:
    """Accept CCv2 wrapper, V1 flat card, or {card: ...} export."""
    if not isinstance(raw, dict):
        return empty_card()
    if raw.get("spec") == "chara_card_v2" and isinstance(raw.get("data"), dict):
        return normalize_card(raw["data"])
    if raw.get("spec") == "chara_card_v3" and isinstance(raw.get("data"), dict):
        return normalize_card(raw["data"])
    if isinstance(raw.get("card"), dict):
        return normalize_card(raw["card"])
    if any(k in raw for k in ("description", "personality", "first_mes", "system_prompt")):
        return normalize_card(raw)
    return empty_card()


def normalize_card(data: dict[str, Any]) -> dict[str, Any]:
    card = empty_card(str(data.get("name") or ""))
    for key in CARD_KEYS:
        if key not in data:
            continue
        val = data[key]
        if key in {"alternate_greetings", "tags"} and isinstance(val, list):
            card[key] = [str(x) for x in val if str(x).strip()]
        elif key == "extensions" and isinstance(val, dict):
            card[key] = copy.deepcopy(val)
        elif key == "character_book" and isinstance(val, dict):
            card[key] = copy.deepcopy(val)
        else:
            card[key] = val if val is not None else card[key]
    return card


def export_v2(card: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_card(card)
    return {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": normalized,
    }


def compile_character_prompt(
    card: dict[str, Any],
    *,
    user_name: str = "the user",
    original: str = "",
) -> tuple[str, str]:
    """Build (system_prompt, post_history_instructions) from a character card."""
    c = normalize_card(card)
    name = (c.get("name") or "Character").strip() or "Character"
    char = name
    user = user_name or "the user"
    base_original = (original or VOICE_RULES).strip()

    parts: list[str] = []
    custom = str(c.get("system_prompt") or "").strip()
    if custom:
        parts.append(_substitute(custom, char=char, user=user, original=base_original).strip())
    else:
        parts.append(f"You are {name}.")
        for label, key in (
            ("Description", "description"),
            ("Personality", "personality"),
            ("Scenario", "scenario"),
        ):
            block = _substitute(str(c.get(key) or ""), char=char, user=user, original=base_original).strip()
            if block:
                parts.append(f"{label}:\n{block}")

    lore = _lorebook_block(c.get("character_book"))
    if lore:
        parts.append(_substitute(lore, char=char, user=user, original=base_original))

    examples = _substitute(str(c.get("mes_example") or ""), char=char, user=user, original=base_original).strip()
    if examples:
        parts.append(f"Example dialogue (match this style):\n{examples}")

    if not custom:
        parts.append(VOICE_RULES)

    post = _substitute(
        str(c.get("post_history_instructions") or ""),
        char=char,
        user=user,
        original="",
    ).strip()

    system = "\n\n".join(p for p in parts if p).strip()
    return system, post


def _strip_roleplay_actions(text: str) -> str:
    """Remove *action* blocks and collapse whitespace for spoken greetings."""
    out = re.sub(r"\*[^*]+\*", " ", text or "")
    out = re.sub(r"\s+", " ", out).strip()
    return out


def compile_greeting(
    card: dict[str, Any],
    *,
    user_name: str = "the user",
) -> str:
    """Build a spoken opening line from first_mes / alternate_greetings."""
    c = normalize_card(card)
    raw = str(c.get("first_mes") or "").strip()
    if not raw:
        alts = c.get("alternate_greetings") or []
        if isinstance(alts, list):
            for alt in alts:
                candidate = str(alt or "").strip()
                if candidate:
                    raw = candidate
                    break
    if not raw:
        return ""
    name = (c.get("name") or "Character").strip() or "Character"
    user = user_name or "the user"
    text = _substitute(raw, char=name, user=user, original="")
    text = _strip_roleplay_actions(text)
    if len(text) > 500:
        text = text[:500].rsplit(" ", 1)[0] + "…"
    return text


def card_from_legacy_prompt(name: str, prompt: str) -> dict[str, Any]:
    card = empty_card(name)
    card["system_prompt"] = prompt.strip()
    return card
