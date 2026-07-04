"""Natural-language detection for image generation requests."""

from __future__ import annotations

import re

_IMAGINE_VERBS = re.compile(
    r"\b(draw|paint|sketch|illustrate|generate|create|make|render|design)\b",
    re.I,
)
_IMAGINE_NOUNS = re.compile(
    r"\b(picture|image|photo|art|portrait|illustration|drawing|painting|pic|poster|wallpaper)\b",
    re.I,
)
_DRAW_OBJECT = re.compile(
    r"\b(?:draw|paint|sketch|illustrate)\s+(?:me\s+)?(?:a|an|the|some)\s+\S",
    re.I,
)

_PROMPT_PREFIXES = (
    r"^(?:please\s+)?(?:can you\s+)?(?:could you\s+)?"
    r"(?:draw|paint|sketch|illustrate)\s+(?:me\s+)?(?:a|an|the|some)?\s*",
    r"^(?:please\s+)?(?:can you\s+)?(?:could you\s+)?"
    r"(?:generate|create|make|render|design)\s+(?:me\s+)?(?:a|an|the|some)?\s*"
    r"(?:picture|image|photo|art|portrait|illustration|drawing|of)?\s*",
)

_MODEL_PATTERNS = (
    (re.compile(r"\bkrea2\b|\bkrea-2\b", re.I), "krea2"),
    (re.compile(r"\bzit\b|\bz-image\b", re.I), "zit"),
    (re.compile(r"\bideogram\b", re.I), "ideogram-local"),
)


def looks_like_imagine_request(text: str) -> bool:
    """True when the user likely wants an image generated, not plain chat."""
    raw = (text or "").strip()
    if not raw:
        return False
    if _IMAGINE_VERBS.search(raw) and _IMAGINE_NOUNS.search(raw):
        return True
    if _DRAW_OBJECT.search(raw):
        return True
    return False


def extract_imagine_prompt(text: str) -> str:
    """Strip leading draw/generate verbs; keep the subject as the Comfy prompt."""
    prompt = (text or "").strip()
    if not prompt:
        return ""
    for pattern in _PROMPT_PREFIXES:
        stripped = re.sub(pattern, "", prompt, count=1, flags=re.I).strip()
        if stripped and stripped != prompt:
            prompt = stripped
            break
    return prompt or (text or "").strip()


def parse_imagine_model_from_text(text: str) -> str | None:
    """Optional model override mentioned in natural language."""
    raw = text or ""
    for pattern, key in _MODEL_PATTERNS:
        if pattern.search(raw):
            return key
    return None
