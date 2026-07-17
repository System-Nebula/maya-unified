"""Browser-safe settings views and secret-update sanitization (SEC-006)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from services.llm.api_keys import (
    clear_persisted_reasoning_api_key,
    clear_runtime_api_key,
    is_placeholder_api_key,
    stash_reasoning_api_key,
)

# UI masks and placeholders that must never overwrite a stored secret.
_SECRET_MASK_VALUES = frozenset(
    {
        "",
        "********",
        "*********",
        "••••••••",
        "••••",
        "****",
        "<redacted>",
        "[redacted]",
        "redacted",
    }
)

_ROOM_SECTION_ALLOWLIST = (
    "delivery",
    "personality",
    "detection",
    "audio",
    "voice",
    "reasoning",
    "vrm",
    "imagine",
)

_VOICE_DROP_KEYS = frozenset({"ref_audio", "ref_text"})
_REASONING_DROP_KEYS = frozenset({"api_key"})
_DISCORD_ROOM_KEYS = frozenset(
    {
        "enabled",
        "guild_id",
        "auto_reply",
        "attach_voice",
        "voice_listen",
    }
)


def is_secret_mask(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    lower = text.lower()
    if lower in _SECRET_MASK_VALUES or lower in {"lm-studio", "vllm-local", "local-model"}:
        return True
    if set(text) <= {"*", "•", "·"}:
        return True
    return False


def to_public_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Return a deep copy safe for browser/SSE/room APIs (no raw secrets)."""
    out = deepcopy(settings or {})

    discord = out.get("discord")
    if isinstance(discord, dict):
        token = str(discord.pop("token", "") or "").strip()
        discord.pop("youtube_cookies_file", None)
        configured = bool(token) or bool(discord.get("token_configured"))
        discord["token_configured"] = configured

    reasoning = out.get("reasoning")
    if isinstance(reasoning, dict):
        key = str(reasoning.pop("api_key", "") or "").strip()
        configured = bool(reasoning.get("api_key_configured")) or (
            bool(key) and not is_placeholder_api_key(key)
        )
        reasoning["api_key_configured"] = configured

    platform = out.get("platform")
    if isinstance(platform, dict):
        url = str(platform.pop("database_url", "") or "").strip()
        platform["database_url_configured"] = bool(url) or bool(
            platform.get("database_url_configured")
        )

    return out


def sanitize_settings_patch(
    patch: dict[str, Any] | None,
    *,
    operator_id: str | None = None,
) -> dict[str, Any]:
    """Normalize a settings update before merge.

    - omitted secrets: unchanged
    - mask / placeholder: ignored (not merged)
    - real value: kept for merge / stash
    - clear_* flags: delete stored secret
    """
    if not isinstance(patch, dict):
        return {}
    out = deepcopy(patch)

    reasoning = out.get("reasoning")
    if isinstance(reasoning, dict):
        clear = bool(reasoning.pop("clear_api_key", False) or reasoning.pop("clear_secret", False))
        if clear:
            clear_persisted_reasoning_api_key(operator_id=operator_id)
            clear_runtime_api_key(operator_id=operator_id)
            reasoning["api_key"] = "lm-studio"
            reasoning["api_key_configured"] = False
        elif "api_key" in reasoning:
            key = str(reasoning.get("api_key") or "").strip()
            if is_secret_mask(key) or is_placeholder_api_key(key):
                reasoning.pop("api_key", None)
            else:
                stash_reasoning_api_key(key, operator_id=operator_id)
                reasoning["api_key_configured"] = True
        if not reasoning:
            out.pop("reasoning", None)

    discord = out.get("discord")
    if isinstance(discord, dict):
        clear = bool(discord.pop("clear_token", False) or discord.pop("clear_secret", False))
        if clear:
            discord["token"] = ""
            discord["token_configured"] = False
        elif "token" in discord:
            token = str(discord.get("token") or "").strip()
            if is_secret_mask(token):
                discord.pop("token", None)
            else:
                discord["token_configured"] = True
        if not discord:
            out.pop("discord", None)

    return out


def room_voice_settings_from(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Allowlisted non-secret settings snapshot for a voice room."""
    src = settings or {}
    out: dict[str, Any] = {}
    for key in _ROOM_SECTION_ALLOWLIST:
        section = src.get(key)
        if not isinstance(section, dict):
            continue
        copied = deepcopy(section)
        if key == "voice":
            for drop in _VOICE_DROP_KEYS:
                copied.pop(drop, None)
        if key == "reasoning":
            for drop in _REASONING_DROP_KEYS:
                copied.pop(drop, None)
            copied.pop("api_key_configured", None)
        out[key] = copied

    discord = src.get("discord")
    if isinstance(discord, dict):
        out["discord"] = {
            k: deepcopy(discord[k]) for k in _DISCORD_ROOM_KEYS if k in discord
        }
    return to_public_settings(out)
