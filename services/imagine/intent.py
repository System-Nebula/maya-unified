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

_MUSIC_NOUNS = re.compile(
    r"\b(song|songs|track|tracks|music|playlist|queue|album|artist)\b",
    re.I,
)
_PREVIOUS_TRACK = re.compile(
    r"\b(previous\s+(?:song|track)|last\s+(?:song|track)|back\s+one)\b",
    re.I,
)
_GO_BACK = re.compile(r"\bgo\s+back\b", re.I)
_SKIP_TRACK = re.compile(
    r"\b("
    r"skip(?:\s+(?:the|this|to\s+the))?\s*(?:song|track)|"
    r"next\s+(?:song|track)|"
    r"skip\s+it|"
    r"(?:start|play)\s+(?:the\s+)?next\s+(?:song|track)"
    r")\b",
    re.I,
)
_MUSIC_CONTROL = re.compile(
    r"\b(pause|resume|stop|play|skip|unpause|continue|start)\b",
    re.I,
)


_CLEAR_QUEUE = re.compile(
    r"\b(?:clear|empty|reset|remove|delete|wipe)\b",
    re.I,
)


def classify_music_playback_command(text: str) -> str | None:
    """Return skip|previous|pause|resume|clear for dashboard/discord playback control."""
    raw = (text or "").strip()
    tl = raw.lower()
    if not tl:
        return None
    if _PREVIOUS_TRACK.search(raw) or (_GO_BACK.search(raw) and _MUSIC_NOUNS.search(raw)):
        return "previous"
    if _SKIP_TRACK.search(raw):
        return "skip"
    if _MUSIC_NOUNS.search(raw):
        if _CLEAR_QUEUE.search(raw):
            return "clear"
        if re.search(r"\b(?:pause|stop)\b", tl):
            return "pause"
        if re.search(r"\b(?:resume|unpause|continue)\b", tl):
            return "resume"
    return None


def looks_like_music_playback_request(text: str) -> bool:
    """True when the user likely wants music playback control, not image generation."""
    raw = (text or "").strip()
    if not raw:
        return False
    if classify_music_playback_command(raw):
        return True
    if _MUSIC_NOUNS.search(raw) and _MUSIC_CONTROL.search(raw):
        return True
    return False


def looks_like_imagine_request(text: str) -> bool:
    """True when the user likely wants an image generated, not plain chat."""
    raw = (text or "").strip()
    if not raw:
        return False
    if looks_like_music_playback_request(raw):
        return False
    if looks_like_director_refinement(raw):
        return True
    if _IMAGINE_VERBS.search(raw) and _IMAGINE_NOUNS.search(raw):
        return True
    if _DRAW_OBJECT.search(raw):
        return True
    return False


_DIRECTOR_REFINE = re.compile(
    r"\b(bigger|smaller|inpaint|edit|fix|change|adjust|refine|more\s+runescape|"
    r"background|expression|hat|style|upscale|go\s+back|restore|version)\b",
    re.I,
)


def looks_like_director_refinement(text: str) -> bool:
    """True when user language implies iterative image editing."""
    raw = (text or "").strip()
    if not raw:
        return False
    if looks_like_music_playback_request(raw):
        return False
    return bool(_DIRECTOR_REFINE.search(raw))


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
