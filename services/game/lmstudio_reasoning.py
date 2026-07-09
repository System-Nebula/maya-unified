"""Map game vision reasoning settings to LM Studio Gemma-4 on/off API."""

from __future__ import annotations

# LM Studio toggle-style models (Gemma-4): supported reasoning_effort = on | off
_LM_OFF = frozenset({"none", "off", "false", "0", "no"})
_LM_ON = frozenset({"on", "true", "1", "yes"})
# Graduated labels (DeepSeek, etc.) — treat as on for toggle models.
_LM_GRADUATED = frozenset({"minimal", "low", "medium", "high", "xhigh"})


def normalize_lmstudio_reasoning_effort(
    effort: str | None,
    *,
    enabled: bool,
) -> str:
    """Return ``on`` or ``off`` for LM Studio /v1/chat/completions."""
    if not enabled:
        return "off"
    raw = (effort or "on").strip().lower()
    if raw in _LM_OFF:
        return "off"
    if raw in _LM_ON or raw in _LM_GRADUATED:
        return "on"
    return "on"


def think_prefix_for_model(model: str | None, profile_prefix: str = "") -> str:
    """Optional user-message prefix that triggers Gemma-4 thinking in LM Studio."""
    explicit = (profile_prefix or "").strip()
    if explicit:
        return explicit
    name = (model or "").lower()
    if "gemma" in name and ("4" in name or "gemma-4" in name):
        return "<|think|>"
    return ""
