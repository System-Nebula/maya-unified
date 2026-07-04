"""Vision intent detection and multimodal message assembly."""

from __future__ import annotations

import re
from typing import Any

_VISION_RE = re.compile(
    r"\b(?:"
    r"screen|screenshot|screencap|desktop|display|"
    r"browser tabs?|tabs (?:open|i have|do i have)|what tabs|"
    r"what(?:'s| is) on|what do you see|what you see|look at|"
    r"can you see|do you see|use (?:the|my) screen|"
    r"what am i|what i'?m (?:looking at|showing|sharing)|"
    r"on my (?:screen|monitor|desktop)|share(?:d|ing)? (?:my )?screen|"
    r"read (?:this|what)|what does (?:this|it) say|"
    r"describe (?:this|what|the screen|my screen|what you see)"
    r")\b",
    re.I,
)

# When a fresh frame exists, attach it for short follow-ups about visible UI.
_VISION_FOLLOWUP_RE = re.compile(
    r"\b(?:"
    r"tabs?|browser|desktop|icons?|folders?|files?|windows?|"
    r"name (?:some|them|a few|more)|list (?:them|some|more)|"
    r"what(?:'s| is) (?:there|on (?:it|the desktop|my desktop))|"
    r"not true|look again|check again|you sure|gaslight|"
    r"that('s| is) (?:wrong|not right)|actually|really|more detail|be specific|"
    r"what else|tell me more|you (?:said|mentioned)|please (?:name|list|look)"
    r")\b",
    re.I,
)

_VISION_MODEL_HINTS = (
    "gemma",
    "vl",
    "vision",
    "llava",
    "pixtral",
    "gpt-4o",
    "gpt-4.1",
    "claude-3",
    "qwen2-vl",
    "qwen-vl",
    "qwen3-vl",
    "internvl",
    "moondream",
    "llama-3.2-vision",
    "llama-4",
)

NO_FRAME_HINT = (
    "[System: The user wants you to look at their screen but no screenshot is attached "
    "yet. In character, tell them to hit 'Share screen' in the Vision panel, then ask "
    "again — you may tease them but do not invent what's on their desktop.]"
)

VISION_REPLY_HINT = (
    "[System: A screenshot of the user's screen is attached — you can see it now. "
    "Look at the image and answer using ONLY what is actually visible: browser tab "
    "titles, window names, apps, desktop icons, and readable text. Say when something "
    "is too small to read. You MUST reply in your full personality — witty, smug, "
    "teasing, bratty queen energy — roast or praise what you see like Maya-sama "
    "auditing their screen. Do NOT pretend you cannot see it, refuse to look, or "
    "stall for tribute before describing what's on screen; weave the real details "
    "into your in-character voice. Do NOT invent tabs, files, or apps that are not "
    "in the image.]\n\n"
)


def is_vision_request(text: str) -> bool:
    tl = (text or "").strip()
    if not tl:
        return False
    return bool(_VISION_RE.search(tl))


def is_vision_followup(text: str) -> bool:
    tl = (text or "").strip()
    if not tl:
        return False
    return bool(_VISION_FOLLOWUP_RE.search(tl))


def wants_vision(user_text: str, operator_id: str | None) -> bool:
    """True when this turn should include a screen frame (or a no-frame hint)."""
    if is_vision_request(user_text):
        return True
    if not operator_id or not is_vision_followup(user_text):
        return False
    from services.voice import vision_frames

    return vision_frames.get_frame(operator_id) is not None


def model_supports_vision(model: str, settings: dict | None = None) -> bool:
    reasoning = settings or {}
    cap = reasoning.get("vision_capable", "auto")
    if cap is True or str(cap).lower() == "true":
        return True
    if cap is False or str(cap).lower() == "false":
        return False
    m = (model or "").lower()
    return any(hint in m for hint in _VISION_MODEL_HINTS)


def build_user_content(
    text: str,
    image_data_url: str,
    *,
    reasoning: dict | None = None,
) -> list[dict[str, Any]]:
    url = (image_data_url or "").strip()
    # LM Studio / Gemma mtmd requires a data: URI (raw base64 alone → "Invalid url").
    if url and not url.startswith("data:"):
        url = f"data:image/png;base64,{url}"
    body = f"{VISION_REPLY_HINT}{text}"
    return [
        {"type": "image_url", "image_url": {"url": url}},
        {"type": "text", "text": body},
    ]


def _vision_model_candidates(model: str | None, reasoning: dict) -> list[str]:
    candidates: list[str] = []
    if model:
        candidates.append(str(model))
    rm = str(reasoning.get("model") or "")
    if rm:
        candidates.append(rm)
    if str(reasoning.get("provider", "")).lower() == "litellm":
        lm = str((reasoning.get("litellm") or {}).get("model") or "")
        if lm:
            candidates.append(lm)
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        key = c.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(c)
    return out


def resolve_vision_user_content(
    user_content: str,
    user_text: str,
    operator_id: str | None,
    reasoning: dict | None,
    *,
    model: str | None = None,
) -> Any:
    """Return string or multimodal list for the user message content."""
    if not operator_id or not wants_vision(user_text, operator_id):
        return user_content

    reasoning = reasoning or {}
    if not any(
        model_supports_vision(candidate, reasoning)
        for candidate in _vision_model_candidates(model, reasoning)
    ):
        return user_content

    from services.voice import vision_frames

    frame = vision_frames.get_frame(operator_id)
    if frame:
        return build_user_content(user_content, frame, reasoning=reasoning)
    if is_vision_request(user_text):
        return f"{NO_FRAME_HINT}\n\n{user_content}"
    return user_content
