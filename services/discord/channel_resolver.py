"""Resolve mistranscribed Discord channel names via list matching + LLM."""

from __future__ import annotations

import difflib
import json
import logging
from typing import Any

from services.discord.fuzzy_channels import hint_variants, norm_name, resolve_voice_channel_fuzzy
from services.settings.store import load_settings

log = logging.getLogger("maya-unified.discord")

_VOICE_INTENTS = frozenset({"discord_join_voice"})
_TEXT_INTENTS = frozenset({
    "discord_send_message",
    "discord_read_channel",
    "discord_reply_to_user",
})


def _channel_aliases() -> dict[str, str]:
    raw = load_settings().get("discord", {}).get("voice_channel_aliases") or {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if k and v}


def list_discord_channels(discord: Any) -> tuple[list[str], list[str]]:
    """Return (voice_channel_names, text_channel_names)."""
    try:
        status = discord.status()
    except Exception:  # noqa: BLE001
        return [], []
    if not status.get("connected"):
        return [], []
    voice: list[str] = []
    text: list[str] = []
    for guild in status.get("guilds") or []:
        voice.extend(guild.get("voice_channels") or [])
        text.extend(guild.get("text_channels") or [])
    return sorted(set(voice)), sorted(set(text))


def build_channels_hint(discord: Any, fallback: str = "") -> str:
    voice, text = list_discord_channels(discord)
    if not voice and not text:
        return fallback
    lines = [
        "Pick channel_name from these lists (copy exact spelling):",
        f"Voice channels: {', '.join(voice) if voice else '(none)'}",
    ]
    if text:
        preview = ", ".join(text[:40])
        if len(text) > 40:
            preview += ", …"
        lines.append(f"Text channels: {preview}")
    lines.append(
        "Speech-to-text often mishears channel names (for/4, miles/myles, etc.) — "
        "match user intent to the closest real channel from the lists above."
    )
    return "\n".join(lines)


def _fuzzy_pick(hint: str, candidates: list[str], aliases: dict[str, str]) -> str | None:
    if not hint or not candidates:
        return None
    if hint in candidates:
        return hint
    for variant in hint_variants(hint):
        if variant in candidates:
            return variant
    close = difflib.get_close_matches(hint, candidates, n=1, cutoff=0.55)
    if close:
        return close[0]
    for variant in hint_variants(hint):
        close = difflib.get_close_matches(variant, candidates, n=1, cutoff=0.55)
        if close:
            return close[0]

    class _Ch:
        def __init__(self, name: str) -> None:
            self.name = name

    class _Guild:
        voice_channels = []

    guild = _Guild()
    guild.voice_channels = [_Ch(n) for n in candidates]  # type: ignore[attr-defined]
    match = resolve_voice_channel_fuzzy(guild, hint, aliases)  # type: ignore[arg-type]
    return match.name if match is not None else None


def resolve_channel_name(
    llm: Any,
    hint: str,
    candidates: list[str],
    *,
    kind: str = "voice",
) -> str | None:
    """Fuzzy match first, then a small LLM pick from the live channel list."""
    hint = (hint or "").strip()
    if not hint or not candidates:
        return None

    aliases = _channel_aliases() if kind == "voice" else {}
    fuzzy = _fuzzy_pick(hint, candidates, aliases)
    if fuzzy:
        return fuzzy

    try:
        resp = llm.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "You map mistranscribed Discord channel requests to the real channel. "
                        "Reply with exactly one string copied verbatim from the provided list. "
                        "If nothing fits, reply NONE."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Channel type: {kind}\n"
                        f"User said (STT, may be wrong): {hint!r}\n"
                        f"Available: {json.dumps(candidates, ensure_ascii=False)}\n"
                        "Exact channel name:"
                    ),
                },
            ],
            max_tokens=80,
        )
        pick = (getattr(resp, "content", None) or "").strip().strip('"').strip("'")
        if not pick or pick.upper() == "NONE":
            return None
        if pick in candidates:
            return pick
        for name in candidates:
            if norm_name(pick) == norm_name(name):
                return name
        close = difflib.get_close_matches(pick, candidates, n=1, cutoff=0.72)
        if close:
            return close[0]
    except Exception as exc:  # noqa: BLE001
        log.warning("LLM channel resolve failed: %s", exc)
    return None


def resolve_plan_channel_params(agent: Any, plan: Any) -> None:
    """Fix orchestrator channel_name params using live Discord channel lists."""
    if agent.discord is None or plan is None:
        return
    intent = (getattr(plan, "intent", None) or "").lower()
    params = plan.params
    if not isinstance(params, dict):
        return

    voice, text = list_discord_channels(agent.discord)
    if intent in _VOICE_INTENTS and params.get("channel_name"):
        raw = str(params["channel_name"])
        resolved = resolve_channel_name(agent.llm, raw, voice, kind="voice")
        if resolved and resolved != raw:
            log.info("orchestrator channel resolve: %r -> %r", raw, resolved)
            params["channel_name"] = resolved
    elif intent in _TEXT_INTENTS and params.get("channel_name"):
        raw = str(params["channel_name"])
        resolved = resolve_channel_name(agent.llm, raw, text, kind="text")
        if resolved and resolved != raw:
            log.info("orchestrator channel resolve: %r -> %r", raw, resolved)
            params["channel_name"] = resolved


def extract_join_channel_hint(text: str) -> str:
    """Pull a channel fragment from join-style utterances."""
    import re

    t = (text or "").strip()
    if not t:
        return ""
    patterns = (
        r"(?:join|connect to|get in|hop in|switch to|move to)\s+(?:the\s+)?(?:#)?(.+?)(?:\s+voice|\s+vc)?\s*$",
        r"(?:discord\s+)?(?:voice\s+)?channel\s+(?:named\s+)?(.+?)\s*$",
    )
    for pat in patterns:
        m = re.search(pat, t, re.I)
        if m:
            return m.group(1).strip(" '\".,!?")
    return t
