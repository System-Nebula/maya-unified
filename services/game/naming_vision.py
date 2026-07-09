"""Vision-guided FireRed/LeafGreen name entry — LLM reads screen and picks one action."""

from __future__ import annotations

import logging
import re
from typing import Any

from services.game.llm_json import parse_llm_json_dict
from services.game.naming_playbook import normalize_entered_name

log = logging.getLogger("maya-unified.game.naming_vision")

NAMING_GRID_GUIDE = """
Pokemon FireRed/LeafGreen NAME ENTRY screen.
Uppercase keyboard grid (red/orange cursor highlight shows selected key):
  Row1: A B C [blank] D E F [blank] .
  Row2: G H I [blank] J K L [blank] ,
  Row3: M N O [blank] P Q R S
  Row4: T U V [blank] W X Y Z
Right column: lower | BACK | OK

Controls:
- press_up/down/left/right = move cursor
- press_a = confirm highlighted letter (types it into the box) OR confirm OK when done
- press_b = BACK (delete last letter) — ONLY if the name box has WRONG letters
- ONE button per turn
- You must TYPE each letter with arrows + press_a. The box starts empty.
"""

_ALLOWED_NAMING = frozenset({
    "press_up",
    "press_down",
    "press_left",
    "press_right",
    "press_a",
    "press_b",
})

_ACTION_ALIASES = {
    "a": "press_a",
    "b": "press_b",
    "up": "press_up",
    "down": "press_down",
    "left": "press_left",
    "right": "press_right",
}

# Prose must show underscore slots — never accept bare TARGET echoed from the prompt.
_SLOT_PATTERNS = (
    r"name box[^`\n]{0,80}?`([_A-Z][_A-Z]{0,10})`",
    r"box[^`\n]{0,50}?`([_A-Z][_A-Z]{0,10})`",
    r"state[^`\n]{0,40}?`([_A-Z][_A-Z]{0,10})`",
    r"`([_A-Z][_A-Z]{0,10})`",
)


def extract_json_dict(raw: str) -> dict[str, Any] | None:
    return parse_llm_json_dict(
        raw,
        fallback_keys=("entered", "cursor_on", "action", "done", "on_name_screen", "screen"),
    )


def parse_entered_from_prose(raw: str, *, target: str = "") -> str:
    """Read name-box slots from prose — only patterns with underscores/letters in slots."""
    text = raw or ""
    target = (target or "").strip().upper()

    if re.search(r"\b(empty|blank)\b.{0,30}\bname box\b", text, re.I):
        return ""
    if re.search(r"name box is empty", text, re.I):
        return ""

    for pattern in _SLOT_PATTERNS:
        m = re.search(pattern, text, re.I)
        if not m:
            continue
        slot = m.group(1).upper()
        letters = re.sub(r"[^A-Z]", "", slot)
        # Slot pattern with underscores is trustworthy; bare word matching TARGET alone is not.
        if "_" in slot or (letters and len(letters) < len(target or "X")):
            return letters
        if letters and target and letters != target:
            return letters

    return ""


def parse_action_from_prose(raw: str, allowed: set[str]) -> str | None:
    text = (raw or "").lower()
    for key, action in _ACTION_ALIASES.items():
        if action in allowed and re.search(rf"\bpress[_ ]?{re.escape(key)}\b", text):
            return action
    for action in sorted(allowed, key=len, reverse=True):
        if re.search(rf"\b{re.escape(action)}\b", text, re.I):
            return action
    return None


def normalize_action(raw: str, allowed: set[str]) -> str | None:
    key = (raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key in allowed:
        return key
    mapped = _ACTION_ALIASES.get(key) or (key if key.startswith("press_") else None)
    if mapped and mapped in allowed:
        return mapped
    return None


def pick_naming_action_sync(
    image_bytes: bytes,
    *,
    target: str,
    operator_id: str | None,
    allowed: set[str],
    recent_actions: list[str] | None = None,
    typed_letters: int = 0,
) -> dict[str, Any]:
    """Vision LLM: read name box + cursor, return one game input."""
    import base64

    from services.game.agent_loop import _vision_complete

    target = (target or "").strip().upper()
    naming_allowed = sorted(_ALLOWED_NAMING & allowed) or sorted(_ALLOWED_NAMING)
    recent = ", ".join(recent_actions[-4:]) if recent_actions else "none"

    prompt = (
        f"{NAMING_GRID_GUIDE}\n\n"
        f"TARGET name to spell in the box: {target}\n"
        f"Recent buttons pressed: {recent}\n\n"
        "Look ONLY at the screenshot — not the target string above.\n"
        "1. Read letters currently in the name box (underscores = empty slots, e.g. M___ or empty).\n"
        "2. Read which key the red cursor highlight is on.\n"
        "3. Choose ONE button: move cursor with arrows, press_a to type the highlighted letter.\n\n"
        "CRITICAL: Reply with ONLY this JSON — no other text:\n"
        "{\n"
        '  "entered": "",\n'
        '  "cursor_on": "A",\n'
        f'  "action": "{naming_allowed[0]}",\n'
        '  "done": false\n'
        "}\n"
        "Set done=true ONLY when TARGET is fully visible in the name box AND cursor is on OK."
    )

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}"
                    },
                },
                {"type": "text", "text": prompt},
            ],
        }
    ]

    raw = _vision_complete(messages, operator_id, purpose="naming")
    data = extract_json_dict(raw) or {}
    has_json = bool(data)

    entered_json = normalize_entered_name(str(data.get("entered") or "")) if has_json else ""
    entered = entered_json
    if not entered and has_json and data.get("entered") in (None, ""):
        entered = ""
    elif not entered:
        entered = parse_entered_from_prose(raw, target=target)

    # Reject hallucinated full target unless JSON explicitly provided it with underscores implied typed
    if entered == target and not entered_json:
        entered = parse_entered_from_prose(raw, target=target) or ""

    cursor_on = str(data.get("cursor_on") or "").strip().upper()
    done_explicit = bool(data.get("done")) if has_json else False
    action = normalize_action(str(data.get("action") or ""), set(naming_allowed))
    if not action:
        action = parse_action_from_prose(raw, set(naming_allowed))

    next_letter = target[len(entered) : len(entered) + 1] if entered != target else ""

    # Never skip typing — done only from explicit JSON, and only when box matches target.
    if done_explicit and entered != target:
        done_explicit = False

    if entered_json == target and typed_letters < len(target):
        done_explicit = False
        entered = parse_entered_from_prose(raw, target=target) or entered_json[: max(0, typed_letters)]

    if done_explicit and cursor_on not in ("OK", "") and entered == target:
        if "press_right" in naming_allowed:
            action = "press_right"
        done_explicit = False

    if action == "press_b" and (not entered or target.startswith(entered)):
        action = None

    if (
        action == "press_a"
        and next_letter
        and cursor_on
        and cursor_on not in (next_letter, "OK", "BACK", "BLANK", "")
    ):
        action = None

    # Don't press_a to "confirm" unless cursor is on next letter or OK.
    if action == "press_a" and next_letter and cursor_on and cursor_on != next_letter:
        if cursor_on != "OK":
            action = None

    if not action:
        for arrow in ("press_up", "press_down", "press_left", "press_right"):
            if arrow in naming_allowed:
                action = arrow
                break
        if not action:
            action = naming_allowed[0]

    return {
        "entered": entered,
        "entered_json": entered_json,
        "cursor_on": cursor_on,
        "action": action,
        "done": done_explicit,
        "done_explicit": done_explicit,
        "raw": (raw or "")[:320],
    }
