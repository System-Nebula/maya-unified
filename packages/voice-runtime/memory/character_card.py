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
    "parentheses, or emojis. Never prefix lines with your character name and a "
    "colon (e.g. 'Maya:'). Never repeat the same paragraph or sentence twice."
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


_START_TOKEN_RE = re.compile(r"<\s*START\s*>", re.IGNORECASE)
_PSEUDO_TOOL_CALL_RE = re.compile(
    r"(?:play_avatar_animation|set_avatar_expression|list_avatar_animations|"
    r"list_avatar_expressions)\s*\([^)]*\)",
    re.IGNORECASE,
)
_PSEUDO_SET_EXPR_RE = re.compile(
    r"set_avatar_expression\s*\(\s*mood\s*=\s*['\"]([^'\"]+)['\"]\s*\)",
    re.IGNORECASE,
)
_PSEUDO_PLAY_ANIM_RE = re.compile(
    r"play_avatar_animation\s*\(\s*clip_name\s*=\s*['\"]([^'\"]+)['\"]\s*\)",
    re.IGNORECASE,
)


def strip_wrapping_quotes(text: str) -> str:
    """Remove a single pair of quotes wrapped around the whole reply."""
    body = (text or "").strip()
    if len(body) >= 2 and body[0] == body[-1] and body[0] in "\"'":
        inner = body[1:-1].strip()
        if inner:
            return inner
    return body


def strip_llm_artifacts(text: str) -> str:
    """Drop pseudo tool calls and roleplay control tokens that leak into speech."""
    from tools.text_calls import strip_text_tool_calls

    body = (text or "").strip()
    if not body:
        return ""
    body = _START_TOKEN_RE.sub("", body)
    body = _PSEUDO_TOOL_CALL_RE.sub("", body)
    body = strip_text_tool_calls(body)
    return re.sub(r"\s{2,}", " ", body).strip()


def extract_pseudo_tool_calls(text: str) -> list[tuple[str, dict]]:
    """Parse tool calls the model wrote as plain text."""
    from tools.text_calls import parse_text_tool_calls

    calls: list[tuple[str, dict]] = list(parse_text_tool_calls(text))
    for match in _PSEUDO_SET_EXPR_RE.finditer(text or ""):
        calls.append(("set_avatar_expression", {"mood": match.group(1).strip()}))
    for match in _PSEUDO_PLAY_ANIM_RE.finditer(text or ""):
        calls.append(("play_avatar_animation", {"clip_name": match.group(1).strip()}))
    return calls


_ASTERISK_BLOCK_RE = re.compile(r"\*[^*]+\*")
_LEADING_DELIVERY_ASTERISK_RE = re.compile(r"^\s*\*([^*]{1,60}?)\*\s*", re.IGNORECASE)
_ACTION_START_RE = re.compile(
    r"^\s*(?:flips?|flipping|waves?|waving|lands?|landing|smirks?|smirking|"
    r"grins?|grinning|nods?|nodding|bows?|bowing|dances?|dancing|spins?|spinning|"
    r"jumps?|jumping|leaps?|leaping|struts?|strutting|winks?|winking|giggles?|"
    r"giggling|chuckles?|chuckling|saunters?|stomps?|twirls?|cartwheels?|"
    r"backflips?|kicks?|punches?|slashes?|lunges?|crouches?|stretches?)\b",
    re.IGNORECASE,
)


def peel_leading_delivery_asterisk(text: str) -> tuple[str, str | None]:
    """If a short leading *cue* precedes dialogue, peel it for TTS delivery."""
    raw = (text or "").strip()
    match = _LEADING_DELIVERY_ASTERISK_RE.match(raw)
    if not match:
        return raw, None
    block = match.group(1).strip().rstrip(".")
    rest = raw[match.end() :].strip()
    if not rest or _ACTION_START_RE.match(block) or len(block.split()) > 6:
        return raw, None
    return rest, block


def collapse_immediate_duplicate(text: str) -> str:
    """If the model echoed the same block twice back-to-back, keep one copy."""
    t = (text or "").strip()
    if len(t) < 16:
        return t
    half = len(t) // 2
    if t[:half] == t[half:]:
        return t[:half].strip()
    return t


def strip_dialogue_name_prefix(text: str, *, name: str = "") -> str:
    """Remove leading 'Character:' / 'Maya-sama:' style roleplay labels."""
    body = (text or "").strip()
    if not body:
        return ""
    names = []
    if name.strip():
        names.append(name.strip())
        first = name.strip().split()[0]
        if first and first not in names:
            names.append(first)
    names.extend(("Maya", "Maya-sama"))
    seen: set[str] = set()
    ordered: list[str] = []
    for n in names:
        key = n.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(n)
    if ordered:
        label = "|".join(re.escape(n) for n in ordered)
        pattern = re.compile(rf"^(?:{label})(?:-sama)?\s*:\s*", re.IGNORECASE)
        while True:
            match = pattern.match(body)
            if not match:
                break
            body = body[match.end() :].strip()
    return body


def strip_roleplay_actions(text: str) -> str:
    """Remove *action* blocks; keep spoken dialogue outside (or salvage mis-wrapped lines)."""
    raw = (text or "").strip()
    if not raw:
        return ""
    blocks = [m.group(1).strip() for m in re.finditer(r"\*([^*]+)\*", raw)]
    out = _ASTERISK_BLOCK_RE.sub(" ", raw)
    out = re.sub(r"\s+", " ", out).strip()
    if out:
        return out
    for block in reversed(blocks):
        if len(block) < 8 or _ACTION_START_RE.match(block):
            continue
        if re.search(
            r'[.!?"]|^(?:Hey|Hello|Hi|Oh|Well|So|I[''`]?m|You )',
            block,
            re.IGNORECASE,
        ):
            return block
    return ""


def polish_spoken_reply(text: str, *, name: str = "") -> str:
    """Final pass for text that will be shown and spoken aloud."""
    body = strip_llm_artifacts(text)
    body = collapse_immediate_duplicate(body)
    body = strip_dialogue_name_prefix(body, name=name)
    body = strip_roleplay_actions(body)
    body = strip_wrapping_quotes(body)
    return re.sub(r"\s{2,}", " ", body).strip()


def _strip_roleplay_actions(text: str) -> str:
    return strip_roleplay_actions(text)


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
