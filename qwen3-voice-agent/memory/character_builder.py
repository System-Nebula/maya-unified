"""LLM-powered SillyTavern-style character card generation."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from .character_card import compile_character_prompt, normalize_card
from .user_profile import resolve_user_name

if TYPE_CHECKING:
    from llm import LLMClient

_BUILDER_SYSTEM = """\
You are a character card author for a voice AI assistant (SillyTavern Character Card V2).

Given a short brief, output ONE JSON object with these fields:
- name (string, required)
- description — appearance, background, role
- personality — traits, tone, how they speak
- scenario — current setting or context
- first_mes — how {{char}} would greet {{user}}
- mes_example — example dialogue using <START> blocks with {{user}} and {{char}}
- post_history_instructions — brief reinforcement to stay in character
- tags — array of short strings (e.g. ["comedy", "fantasy"])
- creator_notes — design notes for the human author (not sent to the AI)

Rules:
- Use {{char}} for the character and {{user}} for the human in text fields.
- Leave system_prompt as an empty string — the app compiles prompts from other fields.
- This character will be spoken aloud in short voice replies (one to three sentences).
  Write personality and examples that fit concise spoken dialogue, not long prose.
- Output ONLY valid JSON. No markdown fences, labels, or commentary.
"""


def _parse_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    if fenced:
        raw = fenced.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(raw[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _coerce_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        return [p.strip() for p in value.split(",") if p.strip()]
    return []


def build_character_from_prompt(llm: LLMClient, brief: str) -> dict[str, Any]:
    """Call the LLM and return a normalized character card dict."""
    brief = (brief or "").strip()
    if not brief:
        raise ValueError("prompt is required")

    messages = [
        {"role": "system", "content": _BUILDER_SYSTEM},
        {"role": "user", "content": f"Create a character from this brief:\n\n{brief}"},
    ]
    resp = llm.complete(messages, max_tokens=1400)
    raw = _parse_json_object((resp.content or "").strip())
    if not raw:
        snippet = (resp.content or "").strip()[:240]
        raise ValueError(f"model did not return valid JSON{f': {snippet}' if snippet else ''}")

    if isinstance(raw.get("tags"), str) or isinstance(raw.get("tags"), list):
        raw["tags"] = _coerce_tags(raw.get("tags"))

    card = normalize_card(raw)
    if not (card.get("name") or "").strip():
        card["name"] = "Character"
    card["system_prompt"] = ""
    return card


def build_character_result(llm: LLMClient, brief: str, *, data_dir: str = "") -> dict[str, Any]:
    """Generate a card and compiled prompt preview."""
    from config import CONFIG

    if not data_dir:
        data_dir = CONFIG.memory.resolve_data_dir()
    user_name = resolve_user_name(data_dir)
    card = build_character_from_prompt(llm, brief)
    system, post = compile_character_prompt(card, user_name=user_name)
    if not system.strip():
        raise ValueError("compiled prompt is empty")
    return {
        "ok": True,
        "card": card,
        "system_prompt": system,
        "post_history": post,
        "creator_notes": str(card.get("creator_notes") or ""),
    }
