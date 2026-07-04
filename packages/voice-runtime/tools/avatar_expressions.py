"""VRM avatar facial expression tools — cute mood presets for the browser viewer."""

from __future__ import annotations

import re
from typing import Any, Callable

from .registry import ToolSpec

VALID_MOODS = ("idle", "happy", "excited", "surprised", "angry", "frustrated")

_MOOD_ALIASES: dict[str, str] = {
    "neutral": "idle",
    "calm": "idle",
    "default": "idle",
    "rest": "idle",
    "joy": "happy",
    "smile": "happy",
    "glad": "happy",
    "amused": "happy",
    "delighted": "happy",
    "thrilled": "excited",
    "ecstatic": "excited",
    "shock": "surprised",
    "shocked": "surprised",
    "wow": "surprised",
    "mad": "angry",
    "upset": "angry",
    "annoyed": "angry",
    "irritated": "angry",
    "sad": "frustrated",
    "pout": "frustrated",
    "disappointed": "frustrated",
}


def normalize_mood(raw: str) -> str:
    m = (raw or "").strip().lower()
    if m in VALID_MOODS:
        return m
    return _MOOD_ALIASES.get(m, "idle")


def infer_mood_from_text(text: str) -> str:
    """Pick a cute face mood from assistant reply text (fallback when no tool call)."""
    blob = (text or "").lower()
    if not blob.strip():
        return "idle"
    if re.search(r"\b(wow|omg|whoa|gasp|shock|surpris|no way)\b", blob):
        return "surprised"
    if re.search(r"\b(excited|yay|awesome|amazing|fantastic|let'?s go|woohoo)\b", blob):
        return "excited"
    if re.search(r"\b(haha|lol|hehe|cute|love|yay|glad|delight|grin|smile|happy|joy)\b", blob):
        return "happy"
    if re.search(r"\b(ugh|frustrat|annoying|seriously|disappoint|pout|sigh)\b", blob):
        return "frustrated"
    if re.search(r"\b(angry|mad|furious|rage|how dare|unacceptable)\b", blob):
        return "angry"
    return "idle"


def build_avatar_expression_tools(emit: Callable[..., None]) -> list[ToolSpec]:
    def list_moods(_args: dict) -> dict[str, Any]:
        return {
            "moods": list(VALID_MOODS),
            "summary": (
                "idle — soft neutral rest\n"
                "happy — gentle smile\n"
                "excited — bright eyes + smile\n"
                "surprised — cute wide-eyed look\n"
                "angry — light pout (not scary)\n"
                "frustrated — mild annoyed / disappointed face"
            ),
        }

    def set_mood(args: dict) -> dict[str, Any]:
        mood = normalize_mood(str(args.get("mood") or args.get("expression") or ""))
        if mood not in VALID_MOODS:
            raise ValueError(
                f"Unknown mood {args.get('mood')!r}. "
                f"Use one of: {', '.join(VALID_MOODS)}"
            )
        emit(type="avatar_expression", mood=mood)
        return {"ok": True, "mood": mood}

    return [
        ToolSpec(
            name="list_avatar_expressions",
            description=(
                "List cute VRM face moods Maya can show on the browser avatar: "
                "idle, happy, excited, surprised, angry, frustrated."
            ),
            parameters={"type": "object", "properties": {}},
            handler=list_moods,
            group="avatar",
        ),
        ToolSpec(
            name="set_avatar_expression",
            description=(
                "Set the VRM avatar's facial expression/mood. Use to match how you feel "
                "while replying — e.g. happy when complimented, surprised at news, "
                "frustrated when playfully annoyed. Keep it cute and subtle; do not name "
                "the mood in your spoken reply. Call early in the turn when the emotion "
                "is clear, or alongside play_avatar_animation."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "mood": {
                        "type": "string",
                        "enum": list(VALID_MOODS),
                        "description": "Face to show on the VRM avatar.",
                    },
                },
                "required": ["mood"],
            },
            handler=set_mood,
            group="avatar",
        ),
    ]
