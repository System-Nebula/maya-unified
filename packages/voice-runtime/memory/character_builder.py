"""LLM-powered SillyTavern-style character card generation."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from .character_card import compile_character_prompt, normalize_card
from .user_profile import resolve_user_name

if TYPE_CHECKING:
    from llm import LLMClient

_BUILDER_MAX_TOKENS = 2500

_CARD_STRING_FIELDS = (
    "name",
    "description",
    "personality",
    "scenario",
    "first_mes",
    "mes_example",
    "post_history_instructions",
    "creator_notes",
)

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
- Keep each text field to 1-3 short sentences. A complete compact JSON object is
  more important than exhaustive detail in any single field.
- Escape double quotes inside strings as \\" and use \\n for line breaks.
- Output ONLY valid JSON. No markdown fences, labels, or commentary.
"""

_RETRY_USER = (
    "That response was invalid or incomplete JSON. Reply again with ONE complete, "
    "valid JSON object only. Keep each text field brief (1-3 sentences) so the "
    "full object fits in one reply."
)


def _strip_markdown_fence(text: str) -> str:
    raw = (text or "").strip()
    if not raw.startswith("```"):
        return raw
    raw = re.sub(r"^```(?:json)?\s*", "", raw, count=1, flags=re.I)
    return re.sub(r"\s*```\s*$", "", raw).strip()


def _extract_brace_block(text: str) -> str | None:
    """Return the outermost {...} block, or a truncated block if the model cut off."""
    raw = _strip_markdown_fence(text)
    start = raw.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return raw[start : i + 1]
    return raw[start:]


def _repair_truncated_json(text: str) -> str:
    """Best-effort close for JSON the model stopped generating mid-object."""
    blob = (text or "").strip()
    if not blob.startswith("{"):
        idx = blob.find("{")
        blob = blob[idx:] if idx >= 0 else blob

    in_str = False
    escape = False
    stack: list[str] = []
    for ch in blob:
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch == "}" and stack and stack[-1] == "{":
            stack.pop()
        elif ch == "]" and stack and stack[-1] == "[":
            stack.pop()

    out = blob.rstrip()
    if in_str:
        out += '"'
    elif out.endswith(":"):
        out += ' ""'
    elif out.endswith(","):
        out = out[:-1]
    for opener in reversed(stack):
        out += "]" if opener == "[" else "}"
    return out


def _decode_json_string(raw: str) -> str:
    try:
        return json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        return raw.replace('\\"', '"').replace("\\n", "\n")


def _fallback_extract_fields(text: str) -> dict[str, Any] | None:
    """Pull string fields from broken or truncated JSON as a last resort."""
    blob = _extract_brace_block(text) or text
    out: dict[str, Any] = {}
    for key in _CARD_STRING_FIELDS:
        match = re.search(
            rf'"{re.escape(key)}"\s*:\s*"((?:[^"\\]|\\.)*)(?:"|$)',
            blob,
            re.S,
        )
        if match:
            out[key] = _decode_json_string(match.group(1))
    tags_match = re.search(r'"tags"\s*:\s*\[(.*?)\]', blob, re.S)
    if tags_match:
        out["tags"] = _coerce_tags(re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', tags_match.group(1)))
    return out if (out.get("name") or "").strip() else None


def _parse_json_object(text: str) -> dict[str, Any] | None:
    blob = _extract_brace_block(text)
    if not blob:
        return None
    for candidate in (blob, _repair_truncated_json(blob)):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return _fallback_extract_fields(text)


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
    last_content = ""
    raw: dict[str, Any] | None = None
    for attempt in range(2):
        resp = llm.complete(messages, max_tokens=_BUILDER_MAX_TOKENS)
        last_content = (resp.content or "").strip()
        raw = _parse_json_object(last_content)
        if raw:
            break
        if attempt == 0:
            messages.append({"role": "assistant", "content": last_content})
            messages.append({"role": "user", "content": _RETRY_USER})

    if not raw:
        snippet = last_content[:240]
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
