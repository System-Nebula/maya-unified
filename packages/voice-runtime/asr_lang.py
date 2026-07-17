"""Map ISO / shorthand language codes to Qwen3-ASR full language names."""

from __future__ import annotations

# Names accepted by qwen_asr.validate_language (Qwen3-ASR-0.6B).
QWEN3_ASR_LANGUAGES: tuple[str, ...] = (
    "Chinese",
    "English",
    "Cantonese",
    "Arabic",
    "German",
    "French",
    "Spanish",
    "Portuguese",
    "Indonesian",
    "Italian",
    "Korean",
    "Russian",
    "Thai",
    "Vietnamese",
    "Japanese",
    "Turkish",
    "Hindi",
    "Malay",
    "Dutch",
    "Swedish",
    "Danish",
    "Finnish",
    "Polish",
    "Czech",
    "Filipino",
    "Persian",
    "Greek",
    "Romanian",
    "Hungarian",
    "Macedonian",
)

_QWEN3_BY_CANONICAL = {name.lower(): name for name in QWEN3_ASR_LANGUAGES}

# ISO 639-1 (and common aliases) -> Qwen3 full name.
_ISO_TO_QWEN3: dict[str, str] = {
    "zh": "Chinese",
    "cmn": "Chinese",
    "en": "English",
    "yue": "Cantonese",
    "ar": "Arabic",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "pt": "Portuguese",
    "id": "Indonesian",
    "it": "Italian",
    "ko": "Korean",
    "ru": "Russian",
    "th": "Thai",
    "vi": "Vietnamese",
    "ja": "Japanese",
    "tr": "Turkish",
    "hi": "Hindi",
    "ms": "Malay",
    "nl": "Dutch",
    "sv": "Swedish",
    "da": "Danish",
    "fi": "Finnish",
    "pl": "Polish",
    "cs": "Czech",
    "fil": "Filipino",
    "tl": "Filipino",
    "fa": "Persian",
    "el": "Greek",
    "ro": "Romanian",
    "hu": "Hungarian",
    "mk": "Macedonian",
}


def normalize_qwen3_asr_language(language: str | None) -> str | None:
    """Return a Qwen3-ASR language name, or None for auto-detect."""
    if language is None:
        return None
    raw = str(language).strip()
    if not raw:
        return None

    canonical = _QWEN3_BY_CANONICAL.get(raw.lower())
    if canonical:
        return canonical

    iso = raw.lower().split("-")[0].split("_")[0]
    return _ISO_TO_QWEN3.get(iso)
